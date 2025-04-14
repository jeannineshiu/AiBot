# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import sys
import traceback
from datetime import datetime
from http import HTTPStatus

from aiohttp import web, ClientSession
from aiohttp.web import Request, Response, json_response
from aiohttp_cors import setup as setup_cors, ResourceOptions
from botbuilder.core import (
    TurnContext,
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
)
from botbuilder.core.integration import aiohttp_error_middleware
from botbuilder.schema import Activity, ActivityTypes

from bots import EchoBot
from config import DefaultConfig

CONFIG = DefaultConfig()
PORT = int(os.environ.get("PORT", 8000))

# Setup BotFramework adapter with credentials
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.APP_ID,
    app_password=CONFIG.APP_PASSWORD
)
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Global error handler for the bot
async def on_error(context: TurnContext, error: Exception):
    print(f"\n[on_turn_error] Unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()

    # Send error message to user
    await context.send_activity("The bot encountered an error or bug.")
    await context.send_activity("To keep using the bot, please fix the source code.")

    # Send trace activity for debugging in the Bot Framework Emulator
    if context.activity.channel_id == "emulator":
        trace_activity = Activity(
            label="TurnError",
            name="on_turn_error Trace",
            timestamp=datetime.utcnow(),
            type=ActivityTypes.trace,
            value=f"{error}",
            value_type="https://www.botframework.com/schemas/error",
        )
        await context.send_activity(trace_activity)

ADAPTER.on_turn_error = on_error

# Create bot instance
BOT = EchoBot()

# Endpoint for messages from the Bot Framework
async def messages(req: Request) -> Response:
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    async def call_bot_logic(turn_context: TurnContext):
        await BOT.on_turn(turn_context)

    await ADAPTER.process_activity(activity, auth_header, call_bot_logic)
    return Response(status=HTTPStatus.OK)

# Endpoint to generate Direct Line token
async def get_direct_line_token(req: Request) -> Response:
    """
    API endpoint to exchange the Direct Line secret for a token.
    Note: In production, this should be protected!
    """
    try:
        direct_line_secret = CONFIG.DIRECT_LINE_SECRET
        if not direct_line_secret:
            return json_response(
                {"error": "Direct Line secret is not configured."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

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

# Create the aiohttp web application
APP = web.Application(middlewares=[aiohttp_error_middleware])

# Routes
APP.router.add_post("/api/messages", messages)
APP.router.add_get("/api/directlinetoken", get_direct_line_token)

# Serve static files (e.g., index.html, styles.css)
static_path = os.path.dirname(__file__)
APP.router.add_static("/", static_path, show_index=True)

# Enable CORS for all routes
cors = setup_cors(
    APP,
    defaults={
        "*": ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*"
        )
    },
)
for route in list(APP.router.routes()):
    cors.add(route)

# Run the app
if __name__ == "__main__":
    try:
        web.run_app(APP, host="0.0.0.0", port=PORT)
    except Exception as error:
        raise error
