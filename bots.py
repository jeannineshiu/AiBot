import json
from typing import List, Dict, Any
import traceback

# --- BotBuilder Imports ---
from botbuilder.core import (
    ActivityHandler,  # Use ActivityHandler for easier event routing
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
    class ChatReadRetrieveReadApproach:
        async def run_until_final_call(
            self,
            messages: List[Dict[str, str]],
            overrides: Dict[str, Any],
            auth_claims: Dict[str, Any],
            should_stream: bool = False
        ):
            from typing import Coroutine

            async def dummy_coroutine():
                class DummyChoice:
                    class DummyMessage:
                        content = "RAG approach not loaded correctly."

                    message = DummyMessage()

                class DummyCompletion:
                    choices = [DummyChoice()]

                return DummyCompletion()

            class DummyExtraInfo:
                source_documents = []

            return (DummyExtraInfo(), dummy_coroutine())

class RagBot(ActivityHandler):
    """
    Bot that integrates with a RAG (Retrieval-Augmented Generation) approach.
    """
    def __init__(
        self,
        conversation_state: ConversationState,
        user_state: UserState,  # Optional, but recommended
        rag_approach: ChatReadRetrieveReadApproach
    ):
        if conversation_state is None:
            raise TypeError(
                "[RagBot]: Missing parameter. conversation_state is required but None was given."
            )
        if rag_approach is None:
            raise TypeError(
                "[RagBot]: Missing parameter. rag_approach is required but None was given."
            )

        self.conversation_state = conversation_state
        self.user_state = user_state
        self.rag_approach = rag_approach

        # Create state property accessor for conversation history
        self.conversation_history_accessor = \
            self.conversation_state.create_property("ConversationHistory")
        print("[RagBot] Initialized successfully with ConversationState and RAG approach.")

    async def on_turn(self, turn_context: TurnContext):
        print(f"[on_turn] Activity received: type={turn_context.activity.type}, text={turn_context.activity.text}")
        await super().on_turn(turn_context)
        # Save state changes
        await self.conversation_state.save_changes(turn_context, False)
        if self.user_state:
            await self.user_state.save_changes(turn_context, False)

    async def on_members_added_activity(
        self,
        members_added: List[ChannelAccount],
        turn_context: TurnContext
    ):
        print(f"on_members_added_activity triggered for {len(members_added)} members.")
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Welcome! I'm a RAG bot. Ask me questions based on the indexed documents."
                    )
                )

    async def on_message_activity(self, turn_context: TurnContext):
        if (
            turn_context.activity.type == ActivityTypes.message
            and turn_context.activity.text
        ):
            user_message_text = turn_context.activity.text
            print(f"[on_message_activity] User message received: '{user_message_text}'")

            await turn_context.send_activity(
                Activity(type=ActivityTypes.typing)
            )

            conversation_history = await self.conversation_history_accessor.get(
                turn_context, lambda: []
            ) or [] # 'or []' is okay but redundant with default_factory
            print(f"[on_message_activity] Retrieved conversation history (length): {len(conversation_history)}")

            messages_for_rag = conversation_history + [
                {"role": "user", "content": user_message_text}
            ]

            # --- MODIFICATIONS START ---
            full_response_content = ""  # To store the complete streamed answer
            encountered_error = False   # Flag to track errors
            extra_info = None           # Initialize extra_info
            error_message = "Sorry, I encountered an error while processing your request." # Default error message
            # --- MODIFICATIONS END ---

            try:
                extra_info, chat_coroutine = await self.rag_approach.run_until_final_call(
                    messages=messages_for_rag,
                    overrides={},
                    auth_claims={},
                    should_stream=True, # Request streaming
                )

                print("[on_message_activity] Processing stream...")
                # Iterate through the stream and send chunks
                async for update in chat_coroutine:
                    chunk = update.choices[0].delta.content or ""
                    if chunk:
                        full_response_content += chunk # Aggregate the response
                        # Send chunk immediately
                        await turn_context.send_activity(Activity(type=ActivityTypes.message, text=chunk))
                print("[on_message_activity] Stream finished.")

            except Exception as e:
                encountered_error = True # Set error flag
                print(f"[on_message_activity] Error during RAG call or streaming: {e}")
                traceback.print_exc()
                # Send error message *only* if an error occurred
                await turn_context.send_activity(MessageFactory.text(error_message))

            # --- Send source links if available ---
            # Ensure extra_info was potentially assigned before checking attributes
            if extra_info and hasattr(extra_info, "source_documents") and extra_info.source_documents:
                links: List[str] = []
                for doc in extra_info.source_documents:
                    # Safer access to metadata dictionary and 'source' key
                    metadata = getattr(doc, 'metadata', {})
                    url = metadata.get("source")
                    if url and url not in links:
                        links.append(url)
                if links:
                    link_text = (
                        "🔗 Source links:\n"
                        + "\n".join(f"- {u}" for u in links)
                    )
                    await turn_context.send_activity(
                        MessageFactory.text(link_text)
                    )

            # --- Update conversation history ---
            # Only update history if the stream succeeded AND produced content
            if not encountered_error and full_response_content:
                print(f"[on_message_activity] Updating history with aggregated response (length {len(full_response_content)}).")
                updated_history = (
                    messages_for_rag
                    # Use the aggregated response content for history
                    + [{"role": "assistant", "content": full_response_content}]
                )[-10:] # Apply history limit
                await self.conversation_history_accessor.set(
                    turn_context, updated_history
                )
            elif encountered_error:
                print("[on_message_activity] Skipping history update due to error.")
            else: # Handle case where stream finished successfully but produced no content
                print("[on_message_activity] Skipping history update as streamed response was empty.")

        else:
            # --- Existing logic for unhandled activity types ---
            print(f"[on_message_activity] Unhandled activity type received: {turn_context.activity.type}")
            await turn_context.send_activity(
                f"[{self.__class__.__name__}] "
                f"Unhandled activity type: {turn_context.activity.type}"
            )
