import argparse
import asyncio
import logging
import os
import sys # Import sys for sys.exit()
from typing import Optional, Union

from dotenv import load_dotenv

# --- Azure SDK Imports ---
from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
# Use DefaultAzureCredential for flexibility (checks env vars, az cli, managed identity etc.)
# Also keep AzureDeveloperCliCredential if needed by specific prepdocslib components, otherwise DefaultAzureCredential is usually sufficient
from azure.identity.aio import AzureDeveloperCliCredential, DefaultAzureCredential
# Removed get_bearer_token_provider as it's used inside setup_embeddings_service if needed

# --- OpenAI Imports ---
try:
    # Assuming openai v1.x+
    from openai import AsyncOpenAI, AsyncAzureOpenAI, RateLimitError
except ImportError:
    print("Please install the 'openai' package (pip install openai>=1.0.0)")
    sys.exit(1)

# --- Rich Logging ---
try:
    from rich.logging import RichHandler
except ImportError:
    print("Please install the 'rich' package (pip install rich)")
    # Fallback to basic handler if rich is not installed
    RichHandler = logging.StreamHandler # type: ignore[misc,assignment]

# --- Custom Lib Imports ---
# Make sure these modules are available relative to this script
try:
    # from load_azd_env import load_azd_env # Replaced with standard python-dotenv
    from prepdocslib.blobmanager import BlobManager
    from prepdocslib.embeddings import (
        AzureOpenAIEmbeddingService,
        OpenAIEmbeddingService,
        OpenAIEmbeddings
    )
    from prepdocslib.fileprocessor import FileProcessor
    from prepdocslib.filestrategy import FileStrategy
    from prepdocslib.listfilestrategy import (
        ListFileStrategy,
        LocalListFileStrategy,
    )
    from prepdocslib.parser import Parser
    print("Attempting to import from prepdocslib.strategy...")
    from prepdocslib.strategy import DocumentAction, SearchInfo, Strategy
    from prepdocslib.textparser import TextParser
    from prepdocslib.textsplitter import SentenceTextSplitter, TextSplitter
except ModuleNotFoundError as e:
    print(f"Error importing custom library modules: {e}")
    print("Please ensure the 'prepdocslib' directory is in the same directory or accessible via PYTHONPATH.")
    sys.exit(1)
# Handle potential rename if EmbeddingService doesn't exist but OpenAIEmbeddings does in user's lib
except ImportError as e:
    if "cannot import name 'EmbeddingService'" in str(e):
         print("Note: Failed to import 'EmbeddingService', trying 'OpenAIEmbeddings' as base type hint.")
         EmbeddingService = OpenAIEmbeddings # type: ignore[misc,assignment]
    elif "cannot import name 'SearchInfo'" in str(e):
         print("ERROR: Failed to import 'SearchInfo' from prepdocslib.strategy.")
         print("Check if 'prepdocslib/strategy.py' defines SearchInfo correctly and its dependencies (like azure-search-documents) are installed.")
         sys.exit(1)
     # ---> 捕獲導入 strategy 模塊本身可能發生的其他錯誤 <---
    elif "prepdocslib.strategy" in str(e):
         print(f"ERROR: An error occurred while importing 'prepdocslib.strategy': {e}")
         print("Check 'prepdocslib/strategy.py' for internal errors or missing dependencies.")
         sys.exit(1)
    else:
          raise # 重新拋出未預料的 ImportError
except Exception as e: # Catch other potential import errors
     print(f"An unexpected error occurred during custom library imports: {e}")
     sys.exit(1)


logger = logging.getLogger("prepdocs") # Renamed logger for clarity
logger.setLevel(logging.INFO) # Default level
# Ensure logger outputs somewhere, RichHandler/StreamHandler added in main block


# --- Utility Functions ---

def clean_key_if_exists(key: Union[str, None]) -> Union[str, None]:
    """Remove leading/trailing whitespace from key if it exists, return None if empty."""
    if key is not None and key.strip():
        return key.strip()
    return None

async def setup_search_info(
    search_service: str,
    index_name: str,
    azure_credential: Optional[AsyncTokenCredential], # Make credential optional if key is provided
    search_key: Optional[str] = None
) -> SearchInfo:
    """Sets up the SearchInfo object for connecting to Azure AI Search."""
    # Validation moved to initialize_services
    endpoint = f"https://{search_service}.search.windows.net/"
    search_creds: Union[AzureKeyCredential, AsyncTokenCredential]
    if search_key:
        logger.info("Using Azure Search Key credential.")
        search_creds = AzureKeyCredential(search_key)
    elif azure_credential:
        logger.info("Using Azure Identity credential for Azure Search.")
        search_creds = azure_credential
    else:
        # This state should ideally not be reached if validation in initialize_services is correct
        raise ValueError("Either Azure credential or Azure Search key must be provided.")

    return SearchInfo(
        endpoint=endpoint,
        credential=search_creds,
        index_name=index_name,
    )

# Corrected setup_blob_manager function
def setup_blob_manager(
    azure_credential: Optional[AsyncTokenCredential],
    storage_account: str,
    storage_container: str,
    storage_resource_group: str, # Required by user's BlobManager
    subscription_id: str,        # Required by user's BlobManager
    storage_key: Optional[str] = None,
) -> Optional[BlobManager]:
    """Sets up the BlobManager for connecting to Azure Blob Storage."""
    # Validation moved to initialize_services
    endpoint = f"https://{storage_account}.blob.core.windows.net"
    blob_creds: Optional[Union[AsyncTokenCredential, str]] = None

    if storage_key:
        logger.info("Using Azure Storage Key credential.")
        blob_creds = storage_key
    elif azure_credential:
        logger.info("Using Azure Identity credential for Azure Storage.")
        blob_creds = azure_credential
    else:
        # Allow proceeding without credential/key if BlobManager class itself handles this possibility
        # or if operations requiring auth aren't used (e.g., read-only public blobs).
        # If BlobManager *requires* auth, instantiation might fail below.
        logger.warning("No Azure credential or Storage key provided for Blob. Operations might fail if auth is required.")

    try:
        # Pass all required arguments as identified by the TypeError
        return BlobManager(
            endpoint=endpoint,
            container=storage_container,
            credential=blob_creds, # Pass credential object or key string
            account=storage_account,
            resourceGroup=storage_resource_group,
            subscriptionId=subscription_id
        )
    except TypeError as e:
         # Catch error if BlobManager signature changed or args are wrong type
         logger.error(f"Failed to instantiate BlobManager. Check BlobManager class definition and arguments: {e}", exc_info=True)
         # Depending on whether BlobManager is critical, either return None or raise
         # For now, return None as per previous logic (allows --skipblobs effectively)
         return None
    except Exception as e:
         logger.error(f"An unexpected error occurred during BlobManager instantiation: {e}", exc_info=True)
         return None


def setup_list_file_strategy(local_files_pattern: str) -> ListFileStrategy:
    """Sets up the strategy to list local files based on a pattern."""
    # Validation moved to initialize_services
    logger.info("Using local files pattern: %s", local_files_pattern)
    return LocalListFileStrategy(path_pattern=local_files_pattern)

# Assuming EmbeddingService is now correctly aliased to OpenAIEmbeddings if needed
def setup_embeddings_service(
    azure_credential: Optional[AsyncTokenCredential],
    openai_host: str,
    openai_model_name: str,
    openai_service: Optional[str],
    openai_deployment: Optional[str],
    openai_dimensions: int,
    openai_api_version: str,
    openai_key: Optional[str], # This is the *effective* key passed in
    openai_org: Optional[str],
) -> Optional['EmbeddingService']: # Use the potentially aliased EmbeddingService type hint
    """Sets up the service to generate embeddings using OpenAI or Azure OpenAI."""
    logger.info("Setting up embeddings service...")
    # Validation moved to initialize_services

    if openai_host.startswith("azure"):
        logger.info("Configuring Azure OpenAI Embedding Service.")
        # Determine credential for Azure OpenAI
        azure_open_ai_credential: Optional[Union[AsyncTokenCredential, AzureKeyCredential]] = None
        if openai_key: # If a key was provided (either via arg or AZURE_OPENAI_API_KEY_OVERRIDE)
            logger.info("Using provided API Key for Azure OpenAI.")
            azure_open_ai_credential = AzureKeyCredential(openai_key)
        elif azure_credential:
            logger.info("Using Azure Identity credential for Azure OpenAI.")
            azure_open_ai_credential = azure_credential
        else:
            # This state should not be reached due to prior validation
             raise ValueError("Azure OpenAI host requires an API key or a working Azure credential.")

        # Instantiate the service (ensure class name matches prepdocslib)
        return AzureOpenAIEmbeddingService(
            open_ai_service=openai_service,
            open_ai_deployment=openai_deployment,
            open_ai_model_name=openai_model_name,
            open_ai_dimensions=openai_dimensions,
            open_ai_api_version=openai_api_version,
            credential=azure_open_ai_credential,
        )
    elif openai_host == "openai":
        logger.info("Configuring OpenAI Embedding Service.")
        if not openai_key:
            # This state should not be reached due to prior validation
            raise ValueError("OpenAI API key required for non-Azure OpenAI host.")

        # Instantiate the service (ensure class name matches prepdocslib)
        return OpenAIEmbeddingService(
            open_ai_model_name=openai_model_name,
            open_ai_dimensions=openai_dimensions,
            credential=openai_key,
            organization=openai_org,
        )
    else:
        raise ValueError(f"Unsupported OPENAI_HOST value: {openai_host}. Use 'azure' or 'openai'.")


def setup_file_processors() -> dict[str, FileProcessor]:
    """Sets up file processors map, simplified for Markdown and Text."""
    text_splitter: TextSplitter = SentenceTextSplitter()
    file_processors = {
        ".md": FileProcessor(TextParser(), text_splitter),
        ".txt": FileProcessor(TextParser(), text_splitter),
    }
    logger.info(f"Configured file processors for: {list(file_processors.keys())}")
    return file_processors

# --- Main Execution Logic ---

async def run_strategy(strategy: Strategy, setup_index: bool = True):
    """Sets up and runs the chosen strategy."""
    # Keep this function as is from previous version

    if setup_index:
        logger.info("Setting up search index...")
        try:
            await strategy.setup()
            logger.info("Search index setup complete.")
        except Exception as e:
            logger.error(f"Error during search index setup: {e}", exc_info=True)
            raise
    else:
        logger.info("Skipping search index setup.")

    logger.info("Running indexing strategy...")
    try:
        await strategy.run()
        logger.info("Indexing strategy run complete.")
    except Exception as e:
        logger.error(f"Error during indexing strategy run: {e}", exc_info=True)
        raise

# Main async function to initialize services and run
async def initialize_and_run(args):
    """Initializes all services based on args and env vars, then runs the strategy."""

    # --- Get Configuration and Validate ---
    logger.info("Reading configuration from environment variables and arguments...")
    search_key = clean_key_if_exists(args.searchkey)
    storage_key = clean_key_if_exists(args.storagekey)
    arg_openai_key = clean_key_if_exists(args.openaiapikey) # Key from command line argument

    # Use os.getenv for safety, provide default None or empty string
    search_service_name = os.getenv("AZURE_SEARCH_SERVICE")
    search_index_name = os.getenv("AZURE_SEARCH_INDEX")
    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT")
    storage_container_name = os.getenv("AZURE_STORAGE_CONTAINER")
    storage_resource_group_name = os.getenv("AZURE_STORAGE_RESOURCE_GROUP")
    subscription_id_val = os.getenv("AZURE_SUBSCRIPTION_ID")
    openai_emb_model_name = os.getenv("AZURE_OPENAI_EMB_MODEL_NAME")
    openai_host = os.getenv("OPENAI_HOST", "azure") # Default to azure
    openai_service_name = os.getenv("AZURE_OPENAI_SERVICE")
    openai_emb_deployment_name = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT")
    openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    openai_dimensions = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", 1536))
    openai_org = os.getenv("OPENAI_ORGANIZATION")
    env_openai_api_key = os.getenv("OPENAI_API_KEY") # Key from environment for OpenAI host
    env_azure_openai_override_key = os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE") # Key override from environment for Azure

    # Validate Required Variables
    required_vars = {
        "AZURE_SEARCH_SERVICE": search_service_name,
        "AZURE_SEARCH_INDEX": search_index_name,
        "AZURE_STORAGE_ACCOUNT": storage_account_name,
        "AZURE_STORAGE_CONTAINER": storage_container_name,
        "AZURE_OPENAI_EMB_MODEL_NAME": openai_emb_model_name,
        "OPENAI_HOST": openai_host,
        "AZURE_STORAGE_RESOURCE_GROUP": storage_resource_group_name,
        "AZURE_SUBSCRIPTION_ID": subscription_id_val,
    }
    missing_vars = [k for k, v in required_vars.items() if not v]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

    # Determine effective OpenAI API key (prioritize arg, then specific env vars)
    effective_openai_key = arg_openai_key
    if not effective_openai_key:
        if openai_host.startswith("azure") and env_azure_openai_override_key:
            logger.info("Using AZURE_OPENAI_API_KEY_OVERRIDE from environment.")
            effective_openai_key = clean_key_if_exists(env_azure_openai_override_key)
        elif openai_host == "openai" and env_openai_api_key:
            logger.info("Using OPENAI_API_KEY from environment.")
            effective_openai_key = clean_key_if_exists(env_openai_api_key)

    # Validate Azure OpenAI Specific Vars
    if openai_host.startswith("azure"):
        if not openai_service_name:
             raise ValueError("AZURE_OPENAI_SERVICE must be set for OPENAI_HOST='azure'.")
        if not openai_emb_deployment_name:
             raise ValueError("AZURE_OPENAI_EMB_DEPLOYMENT must be set for OPENAI_HOST='azure'.")
    # Validate OpenAI Specific Vars (Key check done later based on credential)

    # --- Azure Credential Setup ---
    azure_credential: Optional[AsyncTokenCredential] = None
    # Determine if credential is required (if any service needs it and key is not provided)
    search_needs_cred = not search_key
    storage_needs_cred = not storage_key
    openai_needs_cred = openai_host.startswith("azure") and not effective_openai_key

    if search_needs_cred or storage_needs_cred or openai_needs_cred:
        try:
            tenant_id = os.getenv("AZURE_TENANT_ID")
            logger.info(f"Attempting to get Azure credential (Tenant ID: {tenant_id or 'Default'})...")
            # Using DefaultAzureCredential for flexibility
            azure_credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            # Optional: Test credential (might require async context or specific scope)
            # await azure_credential.get_token("https://management.azure.com/.default")
            logger.info("Azure credential obtained successfully.")
        except Exception as e:
            logger.error(f"Failed to get Azure credential: {e}. Ensure you are logged in ('az login') or required env vars are set, or provide API keys for all services.", exc_info=not isinstance(e, ImportError) and "CredentialNotFoundError" not in str(type(e))) # Avoid noisy trace for common import/not found errors
            # Exit only if a service absolutely required the credential
            if (search_needs_cred or storage_needs_cred or openai_needs_cred):
                 print("\nERROR: Azure credential is required but could not be obtained. Exiting.", file=sys.stderr)
                 sys.exit(1)
        # Final check after attempting credential retrieval
        if openai_host.startswith("azure") and not effective_openai_key and not azure_credential:
             raise ValueError("Azure OpenAI host requires an API key or a working Azure credential.")
        if openai_host == "openai" and not effective_openai_key:
             raise ValueError("OpenAI host requires an API key.")


    # --- Setup Services ---
    logger.info("Initializing Azure services...")
    search_info = await setup_search_info(
        search_service=search_service_name,
        index_name=search_index_name,
        azure_credential=azure_credential,
        search_key=search_key,
    )

    blob_manager = setup_blob_manager(
        azure_credential=azure_credential,
        storage_account=storage_account_name,
        storage_container=storage_container_name,
        storage_resource_group=storage_resource_group_name,
        subscription_id=subscription_id_val,
        storage_key=storage_key,
    )

    list_file_strategy = setup_list_file_strategy(local_files_pattern=args.files)

    embeddings_service = None
    dont_use_vectors = os.getenv("USE_VECTORS", "").lower() == "false"
    if dont_use_vectors:
         logger.info("Vector usage is disabled via USE_VECTORS environment variable.")
    else:
        embeddings_service = setup_embeddings_service(
            azure_credential=azure_credential,
            openai_host=openai_host,
            openai_model_name=openai_emb_model_name,
            openai_service=openai_service_name,
            openai_deployment=openai_emb_deployment_name,
            openai_dimensions=openai_dimensions,
            openai_api_version=openai_api_version,
            openai_key=effective_openai_key,
            openai_org=openai_org,
        )
        if not embeddings_service:
             # This case should ideally be caught by earlier validation, but as a safeguard:
             logger.warning("Failed to set up embeddings service despite vectors being enabled.")
             # Decide if this is critical - for RAG, it usually is.
             # raise ValueError("Embeddings service setup failed.")


    file_processors = setup_file_processors()

    # Determine document action
    if args.removeall:
        document_action = DocumentAction.RemoveAll
    elif args.remove:
        document_action = DocumentAction.Remove
    else:
        document_action = DocumentAction.Add
    logger.info(f"Document Action: {document_action.name}")

    # Skip blob operations if manager is None or skipblobs is True
    effective_skip_blobs = args.skipblobs or (blob_manager is None)
    if effective_skip_blobs:
        logger.info("Skipping Blob Storage operations for FileStrategy.")
    else:
         logger.info("Blob Storage operations enabled for FileStrategy.")


    # --- Strategy Setup ---
    logger.info("Using FileStrategy for ingestion.")
    ingestion_strategy = FileStrategy(
        search_info=search_info,
        list_file_strategy=list_file_strategy,
        blob_manager=blob_manager if not effective_skip_blobs else None, # Pass None if skipping
        file_processors=file_processors,
        document_action=document_action,
        embeddings=embeddings_service, # Pass None if vectors disabled
        category=args.category,
    )

    # --- Run Strategy ---
    skip_index_setup = (document_action == DocumentAction.Remove or document_action == DocumentAction.RemoveAll)
    await run_strategy(ingestion_strategy, setup_index=not skip_index_setup)


# Main script entry point
if __name__ == "__main__":
    # --- Argument Parsing ---
    # Keep parser setup as is from previous version
    parser = argparse.ArgumentParser(
        description="Prepare Markdown documents by extracting content, splitting into sections,"
                    " generating embeddings, uploading to blob storage (optional), and indexing in Azure AI Search."
    )
    parser.add_argument("files", help="Required. Glob pattern for local Markdown files to process (e.g., 'data/**/*.md').",)
    parser.add_argument("--category", help="Optional. Value for the category field in the search index for all sections indexed.",)
    parser.add_argument("--skipblobs", action="store_true", help="Optional. Skip uploading content chunks to Azure Blob Storage.",)
    parser.add_argument("--remove", action="store_true", help="Optional. Remove documents matching the files pattern instead of adding.",)
    parser.add_argument("--removeall", action="store_true",help="Optional. Remove all content from the search index and blob container.",)
    parser.add_argument("--searchkey", required=False, help="Optional. Use Azure AI Search key instead of Azure credential.",)
    parser.add_argument("--storagekey", required=False, help="Optional. Use Azure Blob Storage key instead of Azure credential.",)
    parser.add_argument("--openaiapikey", required=False, help="Optional. Use OpenAI API key (required for OPENAI_HOST='openai') or Azure OpenAI API key override.",)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging.")
    args = parser.parse_args()

    # --- Logging Setup ---
    # Keep logging setup as is from previous version
    logging_handlers: list[logging.Handler] = [RichHandler(rich_tracebacks=True, show_path=False)] if args.verbose else [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S", # Changed format slightly for clarity
        handlers=logging_handlers,
    )
    logging.getLogger("azure.identity._internal.decorators").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)

    logger.info("Starting document preparation script.")

    # --- Load Environment Variables ---
    # Keep dotenv loading as is from previous version
    if load_dotenv(verbose=True):
        logger.info("Loaded environment variables from .env file.")
    else:
        logger.warning("No .env file found or failed to load. Relying on system environment variables.")

    # --- Run Async Initialization and Strategy ---
    try:
        # Pass args to the main async function
        asyncio.run(initialize_and_run(args))
        logger.info("Script finished successfully.")
    except ValueError as ve: # Catch specific validation errors
        logger.error(f"Configuration Error: {ve}")
        print(f"\nERROR: Configuration Error - {ve}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Script failed with an unexpected error: {e}", exc_info=True)
        print(f"\nERROR: Script failed - {e}", file=sys.stderr)
        sys.exit(1)