# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import sys
import traceback
from datetime import datetime
from http import HTTPStatus

from aiohttp import web # type: ignore
from aiohttp.web import Request, Response, json_response
from aiohttp_cors import setup as setup_cors, ResourceOptions
from botbuilder.core import TurnContext, BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.core.integration import aiohttp_error_middleware
from botbuilder.schema import Activity, ActivityTypes

from bots import EchoBot
from config import DefaultConfig

CONFIG = DefaultConfig()

# 設定 BotFrameworkAdapterSettings
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.APP_ID,
    app_password=CONFIG.APP_PASSWORD
)

# 建立新的 Adapter 實例
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Catch-all for errors.
async def on_error(context: TurnContext, error: Exception):
    # This check writes out errors to console log .vs. app insights.
    # NOTE: In production environment, you should consider logging this to Azure
    #       application insights.
    print(f"\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()

    # Send a message to the user
    await context.send_activity("The bot encountered an error or bug.")
    await context.send_activity(
        "To continue to run this bot, please fix the bot source code."
    )
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


ADAPTER.on_turn_error = on_error

# Create the Bot
BOT = EchoBot()


# Listen for incoming requests on /api/messages
async def messages(req: Request) -> Response:
    return await ADAPTER.process(req, BOT)


async def get_direct_line_token(req: Request) -> Response:
    """
    API endpoint to exchange Direct Line secret for a token.
    This should be secured in a production environment.
    """
    try:
        # IMPORTANT: Never expose your Direct Line secret directly in client-side code!
        # This is for demonstration purposes only.
        direct_line_secret = CONFIG.DIRECT_LINE_SECRET
        if not direct_line_secret:
            return json_response({"error": "Direct Line secret not configured"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        # Use the Bot Framework SDK to generate a Direct Line token
        settings = BotFrameworkAdapterSettings(app_id=None, app_password=None) # No need for app ID/password for token generation
        temp_adapter = BotFrameworkAdapter(settings)
        token_response = await temp_adapter.get_direct_line_token(direct_line_secret)

        if "token" in token_response:
            return json_response({"token": token_response["token"]})
        else:
            return json_response({"error": "Failed to retrieve Direct Line token"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    except Exception as e:
        print(f"Error getting Direct Line token: {e}")
        return json_response({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)


# Create the app
APP = web.Application(middlewares=[aiohttp_error_middleware])

# Add routes
APP.router.add_post("/api/messages", messages)
APP.router.add_get("/api/directlinetoken", get_direct_line_token) # 新增獲取 token 的路由

# Serve static files from the "frontend" folder
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
APP.router.add_static("/", frontend_path, show_index=True)

# Enable CORS
cors = setup_cors(APP, defaults={
    "*": ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})
for route in list(APP.router.routes()):
    cors.add(route)

if __name__ == "__main__":
    try:
        web.run_app(APP, host="0.0.0.0", port=CONFIG.PORT)
    except Exception as error:
        raise error