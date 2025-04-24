# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from typing import List, Dict, Any
import traceback

# --- BotBuilder Imports ---
from botbuilder.core import (
    ActivityHandler, # Use ActivityHandler for easier event routing
    TurnContext,
    ConversationState,
    UserState,
    MessageFactory,
)
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount

# --- RAG Imports ---
# Import the specific approach class you are using
try:
    from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
except ModuleNotFoundError:
    print("ERROR: Make sure the 'approaches' module is accessible.")
    # Define a placeholder if import fails to allow basic structure check
    class ChatReadRetrieveReadApproach:
        async def run(self, messages: List[Dict[str, str]], **kwargs):
             return {"answer": "RAG Approach not loaded correctly."}

class RagBot(ActivityHandler):
    """
    Bot that integrates with a RAG (Retrieval-Augmented Generation) approach.
    """
    def __init__(
        self,
        conversation_state: ConversationState,
        user_state: UserState, # Optional, but good practice
        rag_approach: ChatReadRetrieveReadApproach
    ):
        if conversation_state is None:
            raise TypeError(
                "[RagBot]: Missing parameter. conversation_state is required but None was given"
            )
        if rag_approach is None:
             raise TypeError(
                 "[RagBot]: Missing parameter. rag_approach is required but None was given"
             )

        self.conversation_state = conversation_state
        self.user_state = user_state
        self.rag_approach = rag_approach

        # Create state property accessors
        self.conversation_history_accessor = self.conversation_state.create_property("ConversationHistory")

    async def on_turn(self, turn_context: TurnContext):
        # Override default on_turn to save state changes after each turn
        await super().on_turn(turn_context)

        # Save any state changes that might have occurred during the turn.
        await self.conversation_state.save_changes(turn_context, False)
        if self.user_state:
            await self.user_state.save_changes(turn_context, False)

    async def on_members_added_activity(
        self, members_added: List[ChannelAccount], turn_context: TurnContext
    ):
        """ Send a welcome message to the user and tell them what the bot does. """
        for member in members_added:
            # Greet anyone that was not the target (recipient) of this message.
            # Note: This logic doesn't work on all channels! Hacked for now.
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Welcome! I'm a RAG bot. Ask me questions based on the indexed documents."
                    )
                )

    async def on_message_activity(self, turn_context: TurnContext):
        """ Main handler for incoming text messages """
        if turn_context.activity.type == ActivityTypes.message and turn_context.activity.text:
            user_message_text = turn_context.activity.text
            print(f"User message: {user_message_text}")

            # Show typing indicator
            await turn_context.send_activity(Activity(type=ActivityTypes.typing))

            # 1. Get conversation history from state
            conversation_history = await self.conversation_history_accessor.get(turn_context, [])

            # 2. Prepare messages for RAG approach
            messages_for_rag = conversation_history + [{"role": "user", "content": user_message_text}]

            # 3. Call the RAG approach
            try:
                # Context can include overrides if needed, but keep it simple for now
                # Session state is managed by bot state, so pass None or simple ID
                session_state_id = turn_context.activity.conversation.id # Use conversation ID as a simple session identifier
                rag_result = await self.rag_approach.run(
                    messages=messages_for_rag,
                    context={}, # Add overrides here if needed: context={"overrides": {"semantic_ranker": True}}
                    session_state=session_state_id # Pass simple ID, history managed separately
                )
                answer = rag_result.get("answer", "Sorry, I couldn't generate a response.")
                # You could potentially extract sources/citations from rag_result["data_points"]
                # and format them into the response if needed.
                print(f"RAG Answer: {answer}")

            except Exception as e:
                print(f"Error calling RAG approach: {e}")
                traceback.print_exc()
                answer = "Sorry, I encountered an error while processing your request."

            # 4. Send the response to the user
            await turn_context.send_activity(MessageFactory.text(answer))

            # 5. Update conversation history in state
            # Only add messages if the RAG call was somewhat successful (customize this logic)
            if answer != "Sorry, I encountered an error while processing your request.":
                 updated_history = messages_for_rag + [{"role": "assistant", "content": answer}]
                 # Optional: Limit history length
                 # MAX_HISTORY_LENGTH = 10
                 # updated_history = updated_history[-MAX_HISTORY_LENGTH:]
                 await self.conversation_history_accessor.set(turn_context, updated_history)

        else:
            # Handle other activity types like endOfConversation etc. if needed
            await turn_context.send_activity(f"[{self.__class__.__name__}] Unhandled activity type: {turn_context.activity.type}")