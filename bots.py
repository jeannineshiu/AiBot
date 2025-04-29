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
        async def run_until_final_call(self, messages: List[Dict[str, str]], overrides: Dict[str, Any], auth_claims: Dict[str, Any], should_stream: bool = False):
             # Placeholder implementation for structure check if import fails
             from typing import Coroutine
             async def dummy_coroutine():
                 class DummyChoice:
                     class DummyMessage:
                         content = "RAG Approach not loaded correctly."
                     message = DummyMessage()
                 class DummyCompletion:
                     choices = [DummyChoice()]
                 return DummyCompletion()

             class DummyExtraInfo:
                 pass

             return (DummyExtraInfo(), dummy_coroutine())


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
        print("[RagBot] Initialized successfully with ConversationState and RAG approach.")


    async def on_turn(self, turn_context: TurnContext):
        # Override default on_turn to save state changes after each turn
        print(f"[on_turn] Activity received: type={turn_context.activity.type}, text={turn_context.activity.text}")
        await super().on_turn(turn_context)
        # Save any state changes that might have occurred during the turn.
        await self.conversation_state.save_changes(turn_context, False)
        if self.user_state:
            await self.user_state.save_changes(turn_context, False)

    async def on_members_added_activity(
        self, members_added: List[ChannelAccount], turn_context: TurnContext
    ):
        """ Send a welcome message to the user and tell them what the bot does. """
        print(f"on_members_added_activity triggered for {len(members_added)} members.") # Add log
        for member in members_added:
            print(f"  Member ID: {member.id}, Recipient ID: {turn_context.activity.recipient.id}")
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Welcome! I'm a RAG bot. Ask me questions based on the indexed documents."
                    )
                )

    # --- THIS METHOD IS MODIFIED ---
    async def on_message_activity(self, turn_context: TurnContext):
        """ Main handler for incoming text messages """
        if turn_context.activity.type == ActivityTypes.message and turn_context.activity.text:
            user_message_text = turn_context.activity.text
            print(f"[on_message_activity] User message received: '{user_message_text}'") # Log input

            # Show typing indicator
            await turn_context.send_activity(Activity(type=ActivityTypes.typing))

            # 1. Get conversation history from state
            conversation_history = await self.conversation_history_accessor.get(turn_context, [])
            print(f"[on_message_activity] Retrieved conversation history (length): {len(conversation_history)}") # Log history length

            # 2. Prepare messages for RAG approach
            # Ensure format matches ChatCompletionMessageParam (dict with 'role' and 'content')
            messages_for_rag: List[Dict[str, str]] = conversation_history + [{"role": "user", "content": user_message_text}]
            print(f"[on_message_activity] Prepared messages for RAG (total): {len(messages_for_rag)}") # Log total messages

            # 3. Call the RAG approach (using run_until_final_call signature)
            answer = "Sorry, I couldn't generate a response." # Default answer
            try:
                print("[on_message_activity] Calling RAG approach (run_until_final_call)...")
                # Set parameters for run_until_final_call
                should_stream = False # Assuming non-streaming for standard chat
                overrides = {}      # Pass any overrides if needed, e.g., {"top": 5}
                auth_claims = {}    # Pass empty dict if auth claims aren't used for filtering

                # --- Make the corrected call ---
                # Note: run_until_final_call returns a tuple: (extra_info, chat_coroutine)
                extra_info, chat_coroutine = await self.rag_approach.run_until_final_call(
                    messages=messages_for_rag,
                    overrides=overrides,
                    auth_claims=auth_claims,
                    should_stream=should_stream
                )

                # --- Await the result (for non-streaming) ---
                print("[on_message_activity] Awaiting chat completion coroutine...")
                # The coroutine returns an OpenAI ChatCompletion object when awaited
                completion = await chat_coroutine

                # --- Extract the answer ---
                if completion and completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                    answer = completion.choices[0].message.content
                    print(f"[on_message_activity] RAG Answer extracted: {answer[:100]}...") # Log extracted answer (truncated)
                else:
                    print("[on_message_activity] RAG approach returned empty or invalid completion structure.")
                    # Keep the default "Sorry, I couldn't generate a response." answer

                # TODO: Potentially use extra_info for logging, citations etc.
                # print(f"[on_message_activity] RAG Extra Info: {extra_info}")

            except Exception as e:
                print(f"[on_message_activity] Error calling RAG approach or processing result: {e}")
                traceback.print_exc()
                # Keep the default error answer
                answer = "Sorry, I encountered an error while processing your request."

            # 4. Send the response to the user
            print(f"[on_message_activity] Sending response to user: {answer[:100]}...") # Log sending response
            await turn_context.send_activity(MessageFactory.text(answer))

            # 5. Update conversation history in state
            if answer != "Sorry, I encountered an error while processing your request.":
                 updated_history = messages_for_rag + [{"role": "assistant", "content": answer}]
                 # Optional: Limit history length
                 # MAX_HISTORY_LENGTH = 10
                 # updated_history = updated_history[-MAX_HISTORY_LENGTH:]
                 print(f"[on_message_activity] Updating conversation history (new length): {len(updated_history)}") # Log history update
                 await self.conversation_history_accessor.set(turn_context, updated_history)
            else:
                 print("[on_message_activity] Skipping history update due to error.")

        else:
            # Handle other activity types like endOfConversation etc. if needed
            print(f"[on_message_activity] Unhandled activity type received: {turn_context.activity.type}") # Log unhandled
            await turn_context.send_activity(f"[{self.__class__.__name__}] Unhandled activity type: {turn_context.activity.type}")