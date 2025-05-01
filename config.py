#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
from dotenv import load_dotenv

# Load environment variables from .env file (optional, kept for other settings)
load_dotenv()

class DefaultConfig:
    """ Bot Configuration """

    # Server port
    PORT = int(os.environ.get("PORT", 8000))
    APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
    APP_ID = os.environ.get("MicrosoftAppId", "")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
    DIRECT_LINE_SECRET = os.environ.get("DirectLineSecret", "")

    # === Azure OpenAI (hardcoded) ===
    AZURE_OPENAI_SERVICE = "16th--ma3vzbcm-eastus2"
    AZURE_OPENAI_CHATGPT_DEPLOYMENT = "chatgpt4-formybot"
    AZURE_OPENAI_CHATGPT_MODEL = "gpt-4"

    # Optional: if you still use other OpenAI settings
    OPENAI_HOST = os.getenv("OPENAI_HOST", "azure")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AZURE_OPENAI_EMB_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT", "my-embedding-ada")
    AZURE_OPENAI_EMB_MODEL_NAME = os.getenv("AZURE_OPENAI_EMB_MODEL_NAME", "text-embedding-ada-002")
    AZURE_OPENAI_EMB_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS") or 1536)
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-12-01-preview"
    AZURE_OPENAI_API_KEY_OVERRIDE = os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE","3xSUtFvONgV2Vs1283xixuzNcDorI6AihJ34x0wMktZyzELMo69nJQQJ99BDACHYHv6XJ3w3AAAAACOGPjVS")
    AZURE_OPENAI_CUSTOM_URL = os.getenv("AZURE_OPENAI_CUSTOM_URL")
    OPENAI_ORGANIZATION = os.getenv("OPENAI_ORGANIZATION", "")  # Add this line

    # === Azure AI Search ===
    AZURE_SEARCH_SERVICE = os.getenv("AZURE_SEARCH_SERVICE", "")
    AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "")
    AZURE_SEARCH_QUERY_LANGUAGE = os.getenv("AZURE_SEARCH_QUERY_LANGUAGE", "en-us")
    AZURE_SEARCH_QUERY_SPELLER = os.getenv("AZURE_SEARCH_QUERY_SPELLER", "lexicon")
    KB_FIELDS_CONTENT = os.getenv("KB_FIELDS_CONTENT", "content")
    KB_FIELDS_SOURCEPAGE = os.getenv("KB_FIELDS_SOURCEPAGE", "sourcepage")
    AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")

    # === Azure Storage ===
    AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "")
    AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "")

    # === Azure Identity (for passwordless access) ===
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")  # Optional: For user-assigned managed identity
