#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

class DefaultConfig:
    """ Bot Configuration """

    #PORT = 3978
    PORT = int(os.environ.get("PORT", 8000))
    APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
    
    APP_ID = os.environ.get("MicrosoftAppId", "") # Or fetch from secure config
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "") # Or fetch from secure config
    DIRECT_LINE_SECRET = os.environ.get("DirectLineSecret", "") # Or fetch from secure config


    # === Azure OpenAI ===
    OPENAI_HOST = os.getenv("OPENAI_HOST", "azure") # "azure", "azure_custom", "openai", "local"
    AZURE_OPENAI_SERVICE = os.getenv("AZURE_OPENAI_SERVICE")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # For OpenAI API
    AZURE_OPENAI_CHATGPT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT","chatgpt35") # Deployment for chat model
    AZURE_OPENAI_CHATGPT_MODEL = os.environ.get("AZURE_OPENAI_CHATGPT_MODEL", "gpt-35-turbo-instruct")
    AZURE_OPENAI_EMB_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT","my-ada-embedding") # Deployment for embedding model
    AZURE_OPENAI_EMB_MODEL_NAME = os.getenv("AZURE_OPENAI_EMB_MODEL_NAME", "text-embedding-ada-002")
    AZURE_OPENAI_EMB_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS") or 1536)
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-02-01" # Use a recent, appropriate version
    AZURE_OPENAI_API_KEY_OVERRIDE = os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE") # Optional: Use if not using Azure credential
    AZURE_OPENAI_CUSTOM_URL = os.getenv("AZURE_OPENAI_CUSTOM_URL") # Required if OPENAI_HOST="azure_custom"

    # === Azure AI Search ===
    AZURE_SEARCH_SERVICE = os.getenv("AZURE_SEARCH_SERVICE", "")
    AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "")
    AZURE_SEARCH_QUERY_LANGUAGE = os.getenv("AZURE_SEARCH_QUERY_LANGUAGE", "en-us")
    AZURE_SEARCH_QUERY_SPELLER = os.getenv("AZURE_SEARCH_QUERY_SPELLER", "lexicon")
    KB_FIELDS_CONTENT = os.getenv("KB_FIELDS_CONTENT", "content")
    KB_FIELDS_SOURCEPAGE = os.getenv("KB_FIELDS_SOURCEPAGE", "sourcepage")

    # === Azure Storage ===
    AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "")
    AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "")

    # === Azure Identity (for passwordless access) ===
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") # Optional: For user-assigned managed identity