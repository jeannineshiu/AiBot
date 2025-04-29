# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import sys
import traceback
from datetime import datetime
from http import HTTPStatus
import logging # Keep logging import for Azure SDK configuration
from typing import Any, Union, Dict
import time # Import time for simple timing

from aiohttp import web, ClientSession
from aiohttp.web import Request, Response, json_response
from aiohttp_cors import setup as setup_cors, ResourceOptions
from aiohttp import web

# --- BotBuilder Imports ---
from botbuilder.core import (
    TurnContext,
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    ConversationState, # Added
    UserState,         # Added (optional, but good practice)
    MemoryStorage,     # Added (use other storage for production)
)


# Correct import path
from botbuilder.integration.aiohttp import aiohttp_error_middleware, BotFrameworkHttpClient
from botbuilder.schema import Activity, ActivityTypes

# --- RAG Imports (from Quart example structure) ---
from azure.identity.aio import ( # Added
    AzureDeveloperCliCredential,
    ManagedIdentityCredential,
    DefaultAzureCredential, # Use DefaultAzureCredential for flexibility
    get_bearer_token_provider,
)
from azure.identity import CredentialUnavailableError
from azure.search.documents.aio import SearchClient                 # Added
from azure.storage.blob.aio import ContainerClient                 # Added
from openai import AsyncAzureOpenAI, AsyncOpenAI                   # Added
from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
from approaches.promptmanager import PromptyManager
from bots import RagBot
from config import DefaultConfig

# Add this below your imports (or anywhere before you instantiate the approach):
class NoOpAuthHelper:
    """A dummy auth helper that applies no security filter."""
    def build_security_filters(self, overrides, auth_claims):
        # Always return None → no additional search filter
        return None

# --- Logging Helper ---
def log_print(message):
    """Helper function to print messages with timestamps."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] # Milliseconds
    print(f"[{timestamp}] {message}", flush=True) # Ensure logs are flushed immediately

# === Configuration ===
log_print("Loading configuration...")
CONFIG = DefaultConfig()
PORT = CONFIG.PORT
log_print(f"Configuration loaded. Port set to: {PORT}")
# Set logging level for Azure SDKs to avoid excessive noise
logging.getLogger("azure").setLevel(logging.WARNING)
log_print("Azure SDK logging level set to WARNING.")

def init_func():
    """Called by `aiohttp.web` startup command."""
    return create_app()


# === Azure Client Setup ===
# Shared clients dictionary to store initialized clients
AZURE_CLIENTS: Dict[str, Any] = {}
async def setup_azure_clients(app: web.Application):
    """Initializes Azure clients needed for RAG."""
    start_time = time.monotonic()
    log_print(">>> [START] Setting up Azure clients...")
    global AZURE_CLIENTS

    # 1. Azure Credential (Passwordless is recommended)
    log_print("Initializing Azure credential...")
    azure_credential = None
    try:
        # Checks env vars like AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET
        # Also checks for Azure CLI login, VS Code login, etc.
        # For Managed Identity, ensure AZURE_CLIENT_ID is set if using user-assigned MI.
        azure_credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        # Perform a quick check to ensure the credential works
        log_print("Attempting to get token with DefaultAzureCredential...")
        await azure_credential.get_token("https://management.azure.com/.default")
        log_print("Azure credential obtained successfully via DefaultAzureCredential.")
    except CredentialUnavailableError:
        log_print("WARNING: Could not find Azure credentials via DefaultAzureCredential.")
        log_print("Ensure you are logged in ('az login') or environment variables (AZURE_CLIENT_ID, etc.) are set for Service Principal or Managed Identity.")
        # Optionally fall back to API key if needed and configured
        if not CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE and CONFIG.OPENAI_HOST.startswith("azure"):
             log_print("ERROR: Azure OpenAI requires credentials or an API key override, but neither found.")
             raise # Re-raise if no key fallback for Azure OpenAI
        if not CONFIG.OPENAI_API_KEY and not CONFIG.OPENAI_HOST.startswith("azure"):
             log_print("ERROR: Non-Azure OpenAI requires OPENAI_API_KEY, but it's not set.")
             raise # Re-raise if no key fallback for non-Azure OpenAI
        log_print("Attempting to proceed using API keys (if configured)...")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize Azure credential: {e}")
        traceback.print_exc()
        raise

    AZURE_CLIENTS["credential"] = azure_credential
    if azure_credential:
        log_print("Stored Azure credential in clients dictionary.")
    else:
        log_print("Azure credential is None (will rely on keys or SDK defaults).")

    # 2. OpenAI Client
    log_print("Initializing OpenAI client...")
    openai_client = None
    try:
        if CONFIG.OPENAI_HOST.startswith("azure"):
            if not CONFIG.AZURE_OPENAI_SERVICE:
                 raise ValueError("AZURE_OPENAI_SERVICE must be set for Azure OpenAI")
            endpoint = f"https://{CONFIG.AZURE_OPENAI_SERVICE}.openai.azure.com"
            log_print(f"Using Azure OpenAI. Endpoint: {endpoint}")

            if CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE:
                log_print("Using Azure OpenAI API Key override.")
                openai_client = AsyncAzureOpenAI(
                    api_version=CONFIG.AZURE_OPENAI_API_VERSION,
                    azure_endpoint=endpoint,
                    api_key=CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE,
                )
            elif azure_credential:
                log_print("Using Azure credential (token provider) for Azure OpenAI.")
                token_provider = get_bearer_token_provider(azure_credential, "https://cognitiveservices.azure.com/.default")
                openai_client = AsyncAzureOpenAI(
                    api_version=CONFIG.AZURE_OPENAI_API_VERSION,
                    azure_endpoint=endpoint,
                    azure_ad_token_provider=token_provider,
                )
            else:
                 # Should have been caught earlier, but double-check
                 raise ValueError("Azure OpenAI requires either an API Key override or a working Azure credential.")

        elif CONFIG.OPENAI_HOST == "local":
             # Example for local OpenAI-compatible endpoint
             base_url = os.environ.get("OPENAI_BASE_URL")
             if not base_url:
                  raise ValueError("OPENAI_BASE_URL must be set for local OpenAI host")
             log_print(f"Using local OpenAI compatible host. Base URL: {base_url}")
             openai_client = AsyncOpenAI(base_url=base_url, api_key="no-key-required") # Often local models don't need a key
        else: # Assume standard OpenAI API
             if not CONFIG.OPENAI_API_KEY:
                  raise ValueError("OPENAI_API_KEY must be set for non-Azure OpenAI")
             log_print("Using standard OpenAI client.")
             openai_client = AsyncOpenAI(
                api_key=CONFIG.OPENAI_API_KEY,
                organization=CONFIG.OPENAI_ORGANIZATION,  # Ensure this is valid or remove if unnecessary
             )
        AZURE_CLIENTS["openai"] = openai_client
        log_print("OpenAI client initialized successfully.")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize OpenAI client: {e}")
        traceback.print_exc()
        raise

    # 3. Azure AI Search Client
    log_print("Initializing Azure AI Search client...")
    try:
        search_endpoint = f"https://{CONFIG.AZURE_SEARCH_SERVICE}.search.windows.net"
        log_print(f"Using Search endpoint: {search_endpoint}, Index: {CONFIG.AZURE_SEARCH_INDEX}")
        # Use credential if available, otherwise SDK might look for AZURE_SEARCH_KEY env var
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=CONFIG.AZURE_SEARCH_INDEX,
            credential=azure_credential if azure_credential else None, # SDK handles key lookup if credential is None
            credential_scopes=["https://search.azure.com/.default"] if azure_credential else None
        )
        # Optionally add a quick test call if needed, but can slow startup
        # await search_client.get_document_count()
        AZURE_CLIENTS["search"] = search_client
        log_print("Search client initialized successfully.")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize Search client: {e}")
        # Check if it was a credential error and key fallback might work
        if isinstance(e, CredentialUnavailableError) and not azure_credential:
            log_print("Search Credential not found. Ensure AZURE_SEARCH_KEY env var is set if not using credentials.")
        traceback.print_exc()
        raise

    # 4. Azure Blob Storage Client (Optional, needed if RAG approach uses it - Check approach code)
    log_print("Initializing Azure Blob Storage client...")
    try:
        blob_endpoint = f"https://{CONFIG.AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
        log_print(f"Using Blob endpoint: {blob_endpoint}, Container: {CONFIG.AZURE_STORAGE_CONTAINER}")
        # Use credential if available, otherwise SDK might look for AZURE_STORAGE_KEY env var
        blob_container_client = ContainerClient(
            account_url=blob_endpoint,
            container_name=CONFIG.AZURE_STORAGE_CONTAINER,
            credential=azure_credential if azure_credential else None, # SDK handles key lookup if credential is None
            credential_scopes=["https://storage.azure.com/.default"] if azure_credential else None
        )
        # Optionally add a quick test call like get_container_properties
        # await blob_container_client.get_container_properties()
        AZURE_CLIENTS["blob"] = blob_container_client
        log_print("Blob Storage client initialized successfully.")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize Blob Storage client: {e}")
        if isinstance(e, CredentialUnavailableError) and not azure_credential:
            log_print("Blob Credential not found. Ensure AZURE_STORAGE_KEY env var is set if not using credentials.")
        traceback.print_exc()
        raise

    # 5. Instantiate Prompt Manager
    log_print("Initializing PromptyManager...")
    try:
        prompt_manager = PromptyManager()
        AZURE_CLIENTS["prompt_manager"] = prompt_manager # Store it if needed elsewhere
        log_print("PromptyManager initialized successfully.")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize PromptyManager: {e}")
        traceback.print_exc()
        raise

    # 6. Instantiate RAG Approach
    log_print("Initializing RAG Approach (ChatReadRetrieveReadApproach)…")
    try:
        # Replace auth_helper=None with an instance of NoOpAuthHelper()
        no_op_helper = NoOpAuthHelper()

        rag_approach = ChatReadRetrieveReadApproach(
            search_client=AZURE_CLIENTS["search"],
            openai_client=AZURE_CLIENTS["openai"],
            auth_helper=no_op_helper,
            chatgpt_model=CONFIG.AZURE_OPENAI_CHATGPT_MODEL,
            chatgpt_deployment=CONFIG.AZURE_OPENAI_CHATGPT_DEPLOYMENT,
            embedding_model=CONFIG.AZURE_OPENAI_EMB_MODEL_NAME,
            embedding_deployment=CONFIG.AZURE_OPENAI_EMB_DEPLOYMENT,
            embedding_dimensions=CONFIG.AZURE_OPENAI_EMB_DIMENSIONS,
            sourcepage_field=CONFIG.KB_FIELDS_SOURCEPAGE,
            content_field=CONFIG.KB_FIELDS_CONTENT,
            query_language=CONFIG.AZURE_SEARCH_QUERY_LANGUAGE,
            query_speller=CONFIG.AZURE_SEARCH_QUERY_SPELLER,
            prompt_manager=prompt_manager,
        )
        # Force‐inject the helper
        rag_approach.auth_helper = no_op_helper
        AZURE_CLIENTS["rag_approach"] = rag_approach
        log_print("RAG Approach initialized successfully.")
    except Exception as e:
        log_print(f"ERROR: Failed to initialize RAG Approach: {e}")
        traceback.print_exc()
        raise

    duration = time.monotonic() - start_time
    log_print(f"<<< [END] Azure clients and RAG setup complete. Duration: {duration:.2f} seconds.")
    app["azure_clients"] = AZURE_CLIENTS # Store clients in the app context

async def close_azure_clients(app: web.Application):
    """Closes Azure client sessions."""
    log_print(">>> [START] Closing Azure clients...")
    clients = app.get("azure_clients", {})
    if clients:
        if client := clients.get("openai"):
            await client.close()
            log_print("OpenAI client closed.")
        if client := clients.get("search"):
            await client.close()
            log_print("Search client closed.")
        if client := clients.get("blob"):
            await client.close()
            log_print("Blob Storage client closed.")
        if client := clients.get("credential"):
             # For DefaultAzureCredential or specific credentials like ManagedIdentityCredential
             if hasattr(client, "close"):
                await client.close()
                log_print("Azure credential closed.")
    log_print("<<< [END] Azure clients closed.")

# === BotFramework Setup ===
log_print("Setting up BotFrameworkAdapter...")
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.APP_ID,
    app_password=CONFIG.APP_PASSWORD
)
ADAPTER = BotFrameworkAdapter(SETTINGS)
log_print("BotFrameworkAdapter created.")

log_print("Setting up Bot State (MemoryStorage, UserState, ConversationState)...")
# Create MemoryStorage, UserState and ConversationState (Use different storage for prod)
MEMORY = MemoryStorage()
USER_STATE = UserState(MEMORY)
CONVERSATION_STATE = ConversationState(MEMORY)
log_print("Bot State created.")

# Catch-all for errors.
async def on_error(context: TurnContext, error: Exception):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_print(f"\n!!! [{timestamp}] [on_turn_error] unhandled error: {error}")
    traceback.print_exc()

    # Send a message to the user
    try:
        await context.send_activity("The bot encountered an error or bug. Please try again later.")
        await context.send_activity(f"Error details (for debugging): {str(error)}") # Send limited error info
    except Exception as e:
        log_print(f"!!! Error sending error message to user: {e}")

    # Send a trace activity if we're talking to the Bot Framework Emulator
    if context.activity.channel_id == "emulator":
        trace_activity = Activity(
            label="TurnError",
            name="on_turn_error Trace",
            timestamp=datetime.utcnow(),
            type=ActivityTypes.trace,
            value=f"{error}",
            value_type="https://www.botframework.com/schemas/error",
        )
        try:
            await context.send_activity(trace_activity)
        except Exception as e:
            log_print(f"!!! Error sending trace activity to emulator: {e}")

    # Consider *not* clearing state automatically unless absolutely necessary
    # await CONVERSATION_STATE.delete(context)


ADAPTER.on_turn_error = on_error
log_print("BotFrameworkAdapter error handler set.")

# Create the Bot (injecting dependencies)
# Note: Bot creation is delayed until after clients are set up via on_startup
BOT: RagBot = None

# === Web Application Setup ===
# Listen for incoming requests on /api/messages.
async def messages(req: Request) -> Response:
    # Main bot message handler.
    if "application/json" not in req.content_type:
        log_print(f"Unsupported media type received: {req.content_type}")
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "") # Use .get for safety

    # Ensure BOT is initialized (should be handled by startup sequence)
    if BOT is None:
         log_print("ERROR: /api/messages called but Bot not initialized. Check startup sequence.")
         return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR, text="Bot not ready")

    try:
        # Use BotFrameworkHttpClient provided by the adapter for outgoing requests
        # Pass the app context containing clients to the bot logic via the adapter
        log_print(f"Processing activity ID: {activity.id}") # Log incoming activity
        response = await ADAPTER.process_activity(activity, auth_header, BOT.on_turn) # Removed context_app_bindings, state/clients are injected into BOT instance
        if response:
            log_print(f"Responding to activity ID: {activity.id} with status {response.status}")
            return response
        log_print(f"Activity ID: {activity.id} processed, no response to send (status OK).")
        return Response(status=HTTPStatus.OK)
    except Exception as exception:
        log_print(f"!!! ERROR processing activity ID {activity.id}: {exception}")
        traceback.print_exc() # Log the full traceback
        # Let the adapter's on_error handler manage user notification if possible,
        # but return a server error status.
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR, text="Error processing message.")

# Endpoint to generate Direct Line token (Keep if using Web Chat)
async def get_direct_line_token(req: Request) -> Response:
    log_print("Request received for /api/directlinetoken")
    try:
        direct_line_secret = CONFIG.DIRECT_LINE_SECRET
        if not direct_line_secret:
            log_print("ERROR: Direct Line secret is not configured.")
            return json_response(
                {"error": "Direct Line secret is not configured."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # Use the BotFrameworkHttpClient from the adapter if possible for consistency,
        # otherwise use a new ClientSession. Using new session here for simplicity.
        token_parameters = {
            "user": {
                "id": "dl_" + os.urandom(16).hex(),
                "name": "WebChatUser",
            }
        }
        # DL token endpoint is static
        dl_endpoint = "https://directline.botframework.com/v3/directline/tokens/generate"
        log_print(f"Generating Direct Line token via POST to {dl_endpoint}")
        async with ClientSession() as session:
             headers = {
                 "Authorization": f"Bearer {direct_line_secret}",
                 "Content-Type": "application/json",
             }
             async with session.post(dl_endpoint, headers=headers, json=token_parameters) as response:
                 log_print(f"Direct Line token generation response status: {response.status}")
                 if response.status == 200:
                     token_response = await response.json()
                     log_print("Direct Line token generated successfully.")
                     # Avoid logging the token itself for security
                     return json_response({"token": token_response["token"]})
                 else:
                     error_text = await response.text()
                     log_print(f"ERROR generating Direct Line token: {response.status} - {error_text}")
                     return json_response(
                         {"error": "Failed to retrieve Direct Line token."},
                         status=HTTPStatus.INTERNAL_SERVER_ERROR,
                     )
    except Exception as e:
        log_print(f"!!! Exception in get_direct_line_token: {e}")
        traceback.print_exc()
        return json_response(
            {"error": "Internal server error generating Direct Line token."},
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

# === Health Check Handler ===
async def health_check_handler(request: web.Request) -> web.Response:
    """
    Handles /health requests, checking the application's health status.
    """
    log_print("Request received for /health")
    app = request.app
    azure_clients = app.get("azure_clients")
    bot_instance = app.get("bot_instance") # Retrieve BOT instance

    is_healthy = True
    status_text = "OK"
    status_code = HTTPStatus.OK # Use HTTPStatus for consistency

    # Check 1: Azure clients and RAG approach
    if not azure_clients or \
       not azure_clients.get("openai") or \
       not azure_clients.get("search") or \
       not azure_clients.get("rag_approach"):
        is_healthy = False
        status_text = "Error: Required Azure clients or RAG approach not initialized."
        status_code = HTTPStatus.SERVICE_UNAVAILABLE # 503
        log_print(f"[Health Check] Unhealthy: {status_text}")

    # Check 2: Bot instance
    if is_healthy and not bot_instance:
        is_healthy = False
        status_text = "Error: Bot instance not created."
        status_code = HTTPStatus.SERVICE_UNAVAILABLE # 503
        log_print(f"[Health Check] Unhealthy: {status_text}")

    # Add more checks here if needed (e.g., ping external dependencies)

    if is_healthy:
        log_print("[Health Check] Status: OK")
        return web.Response(status=status_code, text=status_text)
    else:
        # Log already happened above when setting status_text
        return web.Response(status=status_code, text=status_text)

# === App Initialization and Startup/Shutdown Logic ===
async def on_startup(app: web.Application):
    """ Executes when the application starts"""
    start_time = time.monotonic()
    log_print(">>> [START] Application on_startup...")
    log_print("Calling setup_azure_clients...")
    await setup_azure_clients(app)
    log_print("setup_azure_clients completed.")

    # Now that clients are ready, instantiate the bot
    global BOT
    azure_clients = app.get("azure_clients", {})
    rag_approach = azure_clients.get("rag_approach")
    if not rag_approach:
        log_print("!!! FATAL ERROR: RAG Approach not found in azure_clients after setup.")
        # Exit forcefully to prevent the app from starting in a broken state
        sys.exit("FATAL: RAG Approach failed to initialize.")

    log_print("Instantiating RagBot...")
    try:
        # Pass state and RAG approach to the bot constructor
        BOT = RagBot(CONVERSATION_STATE, USER_STATE, rag_approach)
        app["bot_instance"] = BOT # Store the Bot instance in the app context
        log_print("RagBot instance created and stored in app context.")
    except Exception as e:
        log_print(f"!!! FATAL ERROR: Failed to instantiate RagBot: {e}")
        traceback.print_exc()
        sys.exit("FATAL: RagBot instantiation failed.")

    duration = time.monotonic() - start_time
    log_print(f"<<< [END] Application on_startup complete. Duration: {duration:.2f} seconds.")

async def on_shutdown(app: web.Application):
    """ Executes when the application shutdowns"""
    start_time = time.monotonic()
    log_print(">>> [START] Application on_shutdown...")
    await close_azure_clients(app)
    duration = time.monotonic() - start_time
    log_print(f"<<< [END] Application on_shutdown complete. Duration: {duration:.2f} seconds.")

def create_app() -> web.Application:
    """Creates the main AIOHTTP application."""
    log_print(">>> [START] Creating AIOHTTP application (create_app)...")
    app = web.Application(middlewares=[aiohttp_error_middleware])
    log_print("AIOHTTP error middleware added.")

    # Add routes
    log_print("Adding application routes...")
    app.router.add_post("/api/messages", messages)
    log_print("Route added: POST /api/messages")
    app.router.add_get("/api/directlinetoken", get_direct_line_token) # Keep if needed
    log_print("Route added: GET /api/directlinetoken")
    app.router.add_get("/health", health_check_handler)
    log_print("Route added: GET /health")


    # Serve static files (if you have a web chat frontend)
    # Ensure this path is correct for your deployment structure
    static_path = os.path.join(os.path.dirname(__file__), "static") # Example: Assume static files are in a 'static' subfolder
    if os.path.isdir(static_path):
        app.router.add_static("/", static_path, show_index=True, name='static')
        log_print(f"Serving static files from: {static_path}")

        index_path = os.path.join(static_path, "index.html")
        if os.path.exists(index_path):
            async def serve_index(request):
                return web.FileResponse(index_path)
            app.router.add_get("/", serve_index)
            log_print("Route added: GET / => index.html")
        else:
            log_print("Warning: index.html not found in static path.")



    # Add startup and shutdown handlers
    log_print("Adding on_startup and on_shutdown handlers...")
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # CORS setup (adjust origins as needed for your frontend)
    log_print("Configuring CORS...")
    cors = setup_cors(
        app,
        defaults={
            "*": ResourceOptions(
                allow_credentials=True, expose_headers="*", allow_headers="*"
            )
        },
    )
    for route in list(app.router.routes()):
        cors.add(route)
    log_print("CORS configured for all routes.")

    log_print("<<< [END] AIOHTTP application created.")
    return app

# === Run the App ===
if __name__ == "__main__":
    log_print("== Starting application execution in __main__ ==")
    log_print("Creating AIOHTTP app instance...")
    APP = create_app()
    log_print("AIOHTTP app instance created.")
    try:
        log_print(f"Attempting to start web server on host 0.0.0.0, port {PORT}...")
        web.run_app(APP, host="0.0.0.0", port=PORT, access_log=None) # access_log=None reduces console noise
        # If run_app returns cleanly (e.g., manual shutdown), this might be reached.
        log_print("<<< Web server stopped cleanly. >>>")
    except Exception as error:
        # This catches errors during server startup (e.g., port conflict)
        # or potentially unhandled exceptions during runtime if not caught elsewhere.
        log_print(f"!!! FATAL ERROR during web.run_app: {error}")
        traceback.print_exc()
        # Optional: Exit with a non-zero code to indicate failure
        sys.exit(f"FATAL ERROR: Application failed to run - {error}")
    finally:
         # This block will execute even if sys.exit() is called in try/except
         log_print("== Application execution exiting __main__ block. ==")