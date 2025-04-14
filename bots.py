# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from botbuilder.core import Bot, TurnContext

class EchoBot(Bot):
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.members_added:
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    await turn_context.send_activity("Welcome to EchoBot! You can type anything, and I will echo it back to you.")
        elif turn_context.activity.text:
            await turn_context.send_activity(f"You said: '{turn_context.activity.text}'")
