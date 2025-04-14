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
    DIRECT_LINE_SECRET = os.environ.get("DirectLineSecret", "YBINBBR2SyvL6MSMZ68GcK6OSyyNPFfL3shvAmjiwjHSWRcN6PgR9JQQJ99BDACi5YpzAArohAAABAZBS3zmO.2AoI6rnXunvzjecfOqcqDIENnwmLk4IwYUoy225Vnb56P6nyqrb5JQQJ99BDACi5YpzAArohAAABAZBS1vqm") # 請替換為你的 Direct Line secret
