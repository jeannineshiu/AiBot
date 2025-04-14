# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from botbuilder.core import Bot, TurnContext

class EchoBot(Bot):
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.members_added:
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    await turn_context.send_activity("歡迎使用 EchoBot！您可以輸入任何訊息，我會將它回覆給您。")
        elif turn_context.activity.text:
            await turn_context.send_activity(f"您說了：'{turn_context.activity.text}'")