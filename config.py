#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os

""" Bot Configuration """


class DefaultConfig:
    """ Bot Configuration """

    PORT = 3978
    APP_ID = os.environ.get("MicrosoftAppId", "72859357-2b32-4e77-bf95-22dc3b0d3a4c")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "c06cb1e4-e981-49c5-8445-e1e160097927")
    APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
