import json
from typing import List, Dict, Any
import traceback
import logging

# --- BotBuilder Imports ---
from botbuilder.core import (
    ActivityHandler,  # Use ActivityHandler for easier event routing
    TurnContext,
    ConversationState,
    UserState,
    MessageFactory,
)
from botbuilder.schema import ActivityTypes, ChannelAccount
from botbuilder.schema import Activity

# --- Azure SDK Imports (for richer error handling) ---
from azure.core.exceptions import HttpResponseError

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
            should_stream: bool = False,
        ):
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


# Configure a simple logger for easier debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RagBot")


class RagBot(ActivityHandler):
    """Bot that integrates with a RAG (Retrieval-Augmented Generation) approach."""

    def __init__(
        self,
        conversation_state: ConversationState,
        user_state: UserState,  # Optional, but recommended
        rag_approach: ChatReadRetrieveReadApproach,
    ):
        if conversation_state is None:
            raise TypeError("[RagBot]: conversation_state is required but None was given.")
        if rag_approach is None:
            raise TypeError("[RagBot]: rag_approach is required but None was given.")

        self.conversation_state = conversation_state
        self.user_state = user_state
        self.rag_approach = rag_approach

        # Create state property accessor for conversation history
        self.conversation_history_accessor = self.conversation_state.create_property(
            "ConversationHistory"
        )
        logger.info("[RagBot] Initialized with ConversationState and RAG approach.")

    async def on_turn(self, turn_context: TurnContext):
        await super().on_turn(turn_context)
        await self.conversation_state.save_changes(turn_context, False)
        if self.user_state:
            await self.user_state.save_changes(turn_context, False)

    async def on_members_added_activity(
        self, members_added: List[ChannelAccount], turn_context: TurnContext
    ):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Welcome! I'm a RAG bot. Ask me questions based on the indexed documents."
                    )
                )

    async def on_message_activity(self, turn_context: TurnContext):
        if turn_context.activity.type == ActivityTypes.message and turn_context.activity.text:
            user_message = turn_context.activity.text
            # Proper typing indicator
            await turn_context.send_activity(Activity(type=ActivityTypes.typing))

            # Load conversation history
            conversation_history = await self.conversation_history_accessor.get(
                turn_context, lambda: []
            )

            # Add user message
            messages_for_rag = conversation_history + [
                {"role": "user", "content": user_message}
            ]

            # Prepare for streaming
            full_response = ""
            error_occurred = False
            extra_info = None
            generic_error_text = "Sorry, I couldn't process your request. Please try again later."

            try:
                extra_info, stream = await self.rag_approach.run_until_final_call(
                    messages=messages_for_rag,
                    overrides={},
                    auth_claims={},
                    should_stream=True,
                )

                # Stream response chunks
                async for update in stream:
                    chunk = update.choices[0].delta.content or ""
                    if chunk:
                        full_response += chunk
                        await turn_context.send_activity(MessageFactory.text(chunk))

                logger.info("[on_message_activity] Final answer length: %s", len(full_response))

            except HttpResponseError as http_err:
                # Specific handling for Azure SDK errors (e.g., 'Forbidden')
                error_occurred = True
                # Extract useful diagnostic information
                status_code = (
                    http_err.status_code
                    if hasattr(http_err, "status_code") and http_err.status_code is not None
                    else (http_err.response.status_code if http_err.response else "Unknown")
                )
                request_id = (
                    http_err.response.headers.get("x-ms-request-id")
                    if http_err.response and http_err.response.headers
                    else "N/A"
                )
                logger.error(
                    "HttpResponseError caught | status=%s, message=%s, request_id=%s",
                    status_code,
                    str(http_err),
                    request_id,
                )

                # Tell the user (without leaking sensitive info)
                await turn_context.send_activity(
                    MessageFactory.text(
                        f"⚠️ The service returned **{status_code} Forbidden**. "
                        "Please check your credentials/roles and try again. "
                        f"(request-id: {request_id})"
                    )
                )

            except Exception as ex:  # Generic fallback
                error_occurred = True
                traceback.print_exc()
                logger.exception("Unexpected error: %s", ex)
                await turn_context.send_activity(MessageFactory.text(generic_error_text))

            # Fallback if stream was empty
            if not error_occurred and not full_response:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Sorry, I didn't get a response. Could you please rephrase?"
                    )
                )

            # Send source links if available
            if extra_info and getattr(extra_info, "source_documents", None):
                links = []
                for doc in extra_info.source_documents:
                    url = getattr(doc, "metadata", {}).get("source")
                    if url and url not in links:
                        links.append(url)
                if links:
                    link_list = "\n".join(f"- {u}" for u in links)
                    await turn_context.send_activity(
                        MessageFactory.text(f"🔗 Source links:\n{link_list}")
                    )

            # Update history on success
            if not error_occurred and full_response:
                new_history = messages_for_rag + [
                    {"role": "assistant", "content": full_response}
                ]
                # Keep only the last 10 turns to limit token usage
                await self.conversation_history_accessor.set(turn_context, new_history[-10:])
        else:
            await turn_context.send_activity(
                MessageFactory.text(
                    f"Unhandled activity type: {turn_context.activity.type}"
                )
            )
