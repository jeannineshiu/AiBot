# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import sys
import traceback
from datetime import datetime
from http import HTTPStatus
import logging
from typing import Any, Union, Dict

from aiohttp import web, ClientSession
from aiohttp.web import Request, Response, json_response
from aiohttp_cors import setup as setup_cors, ResourceOptions


# --- BotBuilder Imports ---
from botbuilder.core import (
    TurnContext,
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    ConversationState, # Added
    UserState,         # Added (optional, but good practice)
    MemoryStorage,     # Added (use other storage for production)
)


from botbuilder.core.integration import aiohttp_error_middleware, BotFrameworkHttpClient
from botbuilder.schema import Activity, ActivityTypes

# --- RAG Imports (from Quart example structure) ---
from azure.identity.aio import ( # Added
    AzureDeveloperCliCredential,
    ManagedIdentityCredential,
    DefaultAzureCredential, # Use DefaultAzureCredential for flexibility
    get_bearer_token_provider,
)
from azure.core.exceptions import CredentialNotFoundError
from azure.search.documents.aio import SearchClient                 # Added
from azure.storage.blob.aio import ContainerClient                 # Added
from openai import AsyncAzureOpenAI, AsyncOpenAI                   # Added
from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach

from bots import RagBot
from config import DefaultConfig




#PORT = int(os.environ.get("PORT", 8000))
# === Configuration ===
CONFIG = DefaultConfig()
PORT = CONFIG.PORT
# Set logging level for Azure SDKs to avoid excessive noise
logging.getLogger("azure").setLevel(logging.WARNING)

# === Azure Client Setup ===
# Shared clients dictionary to store initialized clients
AZURE_CLIENTS: Dict[str, Any] = {}
async def setup_azure_clients(app: web.Application):
    """Initializes Azure clients needed for RAG."""
    print("Setting up Azure clients...")
    global AZURE_CLIENTS

    # 1. Azure Credential (Passwordless is recommended)
    azure_credential = None
    try:
        # Checks env vars like AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET
        # Also checks for Azure CLI login, VS Code login, etc.
        # For Managed Identity, ensure AZURE_CLIENT_ID is set if using user-assigned MI.
        azure_credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        # Perform a quick check to ensure the credential works
        await azure_credential.get_token("https://management.azure.com/.default")
        print("Azure credential obtained successfully.")
    except CredentialNotFoundError:
        print("ERROR: Could not find Azure credentials.")
        print("Please run 'az login' or configure environment variables for a service principal or managed identity.")
        # Optionally fall back to API key if needed and configured
        if not CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE and CONFIG.OPENAI_HOST.startswith("azure"):
             raise # Re-raise if no key fallback for Azure OpenAI
        if not CONFIG.OPENAI_API_KEY and not CONFIG.OPENAI_HOST.startswith("azure"):
             raise # Re-raise if no key fallback for non-Azure OpenAI
        print("Attempting to proceed with API keys (if configured)...")
    except Exception as e:
        print(f"ERROR: Failed to initialize Azure credential: {e}")
        raise

    AZURE_CLIENTS["credential"] = azure_credential

    # 2. OpenAI Client
    openai_client = None
    try:
        if CONFIG.OPENAI_HOST.startswith("azure"):
            if not CONFIG.AZURE_OPENAI_SERVICE:
                 raise ValueError("AZURE_OPENAI_SERVICE must be set for Azure OpenAI")
            endpoint = f"https://{CONFIG.AZURE_OPENAI_SERVICE}.openai.azure.com"
            print(f"Initializing Azure OpenAI client for endpoint: {endpoint}")

            if CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE:
                print("Using Azure OpenAI API Key override.")
                openai_client = AsyncAzureOpenAI(
                    api_version=CONFIG.AZURE_OPENAI_API_VERSION,
                    azure_endpoint=endpoint,
                    api_key=CONFIG.AZURE_OPENAI_API_KEY_OVERRIDE,
                )
            elif azure_credential:
                print("Using Azure credential (token provider) for Azure OpenAI.")
                token_provider = get_bearer_token_provider(azure_credential, "https://cognitiveservices.azure.com/.default")
                openai_client = AsyncAzureOpenAI(
                    api_version=CONFIG.AZURE_OPENAI_API_VERSION,
                    azure_endpoint=endpoint,
                    azure_ad_token_provider=token_provider,
                )
            else:
                 raise ValueError("Azure OpenAI requires either an API Key override or a working Azure credential.")

        elif CONFIG.OPENAI_HOST == "local":
             # Example for local OpenAI-compatible endpoint
             base_url = os.environ.get("OPENAI_BASE_URL")
             if not base_url:
                  raise ValueError("OPENAI_BASE_URL must be set for local OpenAI host")
             print(f"Initializing local OpenAI client for base URL: {base_url}")
             openai_client = AsyncOpenAI(base_url=base_url, api_key="no-key-required")
        else: # Assume standard OpenAI API
             if not CONFIG.OPENAI_API_KEY:
                  raise ValueError("OPENAI_API_KEY must be set for non-Azure OpenAI")
             print("Initializing standard OpenAI client.")
             openai_client = AsyncOpenAI(
                api_key=CONFIG.OPENAI_API_KEY,
                organization=CONFIG.OPENAI_ORGANIZATION,
             )
        AZURE_CLIENTS["openai"] = openai_client
        print("OpenAI client initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize OpenAI client: {e}")
        raise

    # 3. Azure AI Search Client
    try:
        search_endpoint = f"https://{CONFIG.AZURE_SEARCH_SERVICE}.search.windows.net"
        print(f"Initializing Search client for endpoint: {search_endpoint}")
        # Use credential if available, otherwise SDK might look for AZURE_SEARCH_KEY env var
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=CONFIG.AZURE_SEARCH_INDEX,
            credential=azure_credential if azure_credential else None, # SDK handles key lookup if credential is None
            credential_scopes=["https://search.azure.com/.default"] if azure_credential else None
        )
        AZURE_CLIENTS["search"] = search_client
        print("Search client initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize Search client: {e}")
        raise

    # 4. Azure Blob Storage Client (Optional, needed if RAG approach uses it - Check approach code)
    # ChatReadRetrieveReadApproach doesn't strictly need it unless customized for source lookup
    try:
        blob_endpoint = f"https://{CONFIG.AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
        print(f"Initializing Blob Storage client for endpoint: {blob_endpoint}")
        # Use credential if available, otherwise SDK might look for AZURE_STORAGE_KEY env var
        blob_container_client = ContainerClient(
            account_url=blob_endpoint,
            container_name=CONFIG.AZURE_STORAGE_CONTAINER,
            credential=azure_credential if azure_credential else None, # SDK handles key lookup if credential is None
            credential_scopes=["https://storage.azure.com/.default"] if azure_credential else None
        )
        AZURE_CLIENTS["blob"] = blob_container_client
        print("Blob Storage client initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize Blob Storage client: {e}")
        # Check if it was a credential error and key fallback might work
        if isinstance(e, CredentialNotFoundError) and not azure_credential:
            print("Credential not found, ensure AZURE_STORAGE_KEY env var is set if not using credentials.")
        # Raise the exception as Blob client is considered required
        raise


    # 5. Instantiate RAG Approach
    try:
        # We removed AuthenticationHelper as it's less relevant for bot scenarios
        # Pass None for auth_helper if the approach expects it
        rag_approach = ChatReadRetrieveReadApproach(
            search_client=AZURE_CLIENTS["search"],
            openai_client=AZURE_CLIENTS["openai"],
            auth_helper=None, # Assuming approach can handle None or doesn't need it here
            chatgpt_model=CONFIG.AZURE_OPENAI_CHATGPT_MODEL,
            chatgpt_deployment=CONFIG.AZURE_OPENAI_CHATGPT_DEPLOYMENT, # Required for Azure OpenAI
            embedding_model=CONFIG.AZURE_OPENAI_EMB_MODEL_NAME,
            embedding_deployment=CONFIG.AZURE_OPENAI_EMB_DEPLOYMENT, # Required for Azure OpenAI
            embedding_dimensions=CONFIG.AZURE_OPENAI_EMB_DIMENSIONS,
            sourcepage_field=CONFIG.KB_FIELDS_SOURCEPAGE,
            content_field=CONFIG.KB_FIELDS_CONTENT,
            query_language=CONFIG.AZURE_SEARCH_QUERY_LANGUAGE,
            query_speller=CONFIG.AZURE_SEARCH_QUERY_SPELLER,
            # Pass other parameters if needed by the specific approach constructor
        )
        AZURE_CLIENTS["rag_approach"] = rag_approach
        print("RAG Approach initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize RAG Approach: {e}")
        traceback.print_exc()
        raise

    print("Azure clients and RAG setup complete.")
    app["azure_clients"] = AZURE_CLIENTS # Store clients in the app context

async def close_azure_clients(app: web.Application):
    """Closes Azure client sessions."""
    print("Closing Azure clients...")
    clients = app.get("azure_clients", {})
    if clients:
        if client := clients.get("openai"):
            await client.close()
            print("OpenAI client closed.")
        if client := clients.get("search"):
            await client.close()
            print("Search client closed.")
        if client := clients.get("blob"):
            await client.close()
            print("Blob Storage client closed.")
        if client := clients.get("credential"):
             # For DefaultAzureCredential or specific credentials like ManagedIdentityCredential
             if hasattr(client, "close"):
                await client.close()
                print("Azure credential closed.")
    print("Azure clients closed.")

# === BotFramework Setup ===
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.APP_ID,
    app_password=CONFIG.APP_PASSWORD
)
# Create adapter.
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Create MemoryStorage, UserState and ConversationState (Use different storage for prod)
MEMORY = MemoryStorage()
USER_STATE = UserState(MEMORY)
CONVERSATION_STATE = ConversationState(MEMORY)

# Catch-all for errors.
async def on_error(context: TurnContext, error: Exception):
    # This check writes out errors to console log .vs. app insights.
    # NOTE: In production environment, you should consider logging this to Azure
    #       application insights.
    print(f"\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()

    # Send a message to the user
    await context.send_activity("The bot encountered an error or bug.")
    await context.send_activity("To continue to run this bot, please fix the bot source code.")
    # Send a trace activity if we're talking to the Bot Framework Emulator
    if context.activity.channel_id == "emulator":
        # Create a trace activity that contains the error object
        trace_activity = Activity(
            label="TurnError",
            name="on_turn_error Trace",
            timestamp=datetime.utcnow(),
            type=ActivityTypes.trace,
            value=f"{error}",
            value_type="https://www.botframework.com/schemas/error",
        )
        # Send a trace activity, which will be displayed in Bot Framework Emulator
        await context.send_activity(trace_activity)

    # Clear out state
    # Uncommenting this line causes state change detection issues in the sample
    # await CONVERSATION_STATE.delete(context)


ADAPTER.on_turn_error = on_error

# Create the Bot (injecting dependencies)
# Note: Bot creation is delayed until after clients are set up via on_startup
BOT: RagBot = None

# === Web Application Setup ===
# Listen for incoming requests on /api/messages.
async def messages(req: Request) -> Response:
    # Main bot message handler.
    if "application/json" not in req.content_type:
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers["Authorization"] if "Authorization" in req.headers else ""

    # Ensure BOT is initialized
    if BOT is None:
         print("ERROR: Bot not initialized. Check startup sequence.")
         return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR, text="Bot not ready")

    try:
        # Use BotFrameworkHttpClient provided by the adapter for outgoing requests
        # Pass the app context containing clients to the bot logic via the adapter
        response = await ADAPTER.process_activity(activity, auth_header, BOT.on_turn, context_app_bindings=req.app)
        if response:
            return response
        return Response(status=HTTPStatus.OK)
    except Exception as exception:
        raise exception

# Endpoint to generate Direct Line token (Keep if using Web Chat)
async def get_direct_line_token(req: Request) -> Response:
    # (Your existing get_direct_line_token code remains unchanged)
    # ... (ensure ClientSession is imported: from aiohttp import ClientSession)
    # ... (ensure DefaultConfig has DIRECT_LINE_SECRET)
    try:
        direct_line_secret = CONFIG.DIRECT_LINE_SECRET
        if not direct_line_secret:
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
        async with ClientSession() as session:
             headers = {
                 "Authorization": f"Bearer {direct_line_secret}",
                 "Content-Type": "application/json",
             }
             async with session.post(
                 "https://directline.botframework.com/v3/directline/tokens/generate",
                 headers=headers,
                 json=token_parameters,
             ) as response:
                 if response.status == 200:
                     token_response = await response.json()
                     return json_response({"token": token_response["token"]})
                 else:
                     error_text = await response.text()
                     print(f"Error generating token: {response.status} - {error_text}")
                     return json_response(
                         {"error": "Failed to retrieve Direct Line token."},
                         status=HTTPStatus.INTERNAL_SERVER_ERROR,
                     )
    except Exception as e:
        print(f"Exception in get_direct_line_token: {e}")
        traceback.print_exc(file=sys.stderr)
        return json_response(
            {"error": str(e)},
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


# === App Initialization and Startup/Shutdown Logic ===
async def on_startup(app: web.Application):
    """ Executes when the application starts"""
    await setup_azure_clients(app)
    # Now that clients are ready, instantiate the bot
    global BOT
    azure_clients = app.get("azure_clients", {})
    rag_approach = azure_clients.get("rag_approach")
    if not rag_approach:
        print("FATAL ERROR: RAG Approach not initialized during startup.")
        # You might want to shut down the application here
        sys.exit(1) # Or handle more gracefully

    # Pass state and RAG approach to the bot constructor
    BOT = RagBot(CONVERSATION_STATE, USER_STATE, rag_approach)
    print("Bot instance created.")

async def on_shutdown(app: web.Application):
    """ Executes when the application shutdowns"""
    await close_azure_clients(app)

def create_app() -> web.Application:
    """Creates the main AIOHTTP application."""
    app = web.Application(middlewares=[aiohttp_error_middleware])

    # Add routes
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/api/directlinetoken", get_direct_line_token) # Keep if needed

    # Serve static files (if you have a web chat frontend)
    static_path = os.path.dirname(__file__) # Assumes index.html is in the same dir
    app.router.add_static("/", static_path, show_index=True, follow_symlinks=True)
    print(f"Serving static files from: {static_path}")


    # Add startup and shutdown handlers
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # CORS setup (adjust origins as needed for your frontend)
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

    return app

# === Run the App ===
if __name__ == "__main__":
    APP = create_app()
    try:
        print(f"Starting web server on http://localhost:{PORT}")
        web.run_app(APP, host="0.0.0.0", port=PORT)
    except Exception as error:
        print(f"Error running web app: {error}")
        raise error
