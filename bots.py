import json
from typing import List, Dict, Any
import traceback
import logging
import asyncio
from openai.error import RateLimitError  # imported for catching 429s

# --- BotBuilder Imports ---
from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    UserState,
    MessageFactory,
)
from botbuilder.schema import ActivityTypes, ChannelAccount, Activity

# --- Azure SDK Imports ---
from azure.core.exceptions import HttpResponseError

# --- RAG Imports ---
try:
    from approaches.chatreadretrieveread import ChatReadRetrieveReadApproach
except ModuleNotFoundError:
    print("ERROR: Make sure the 'approaches' module is accessible.")
    class ChatReadRetrieveReadApproach:
        async def run_until_final_call(self, messages, overrides, auth_claims, should_stream=False):
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
            return DummyExtraInfo(), dummy_coroutine()

# --------------------- logging setup ---------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RagBot")


class RagBot(ActivityHandler):
    """Bot that integrates with a RAG (Retrieval‑Augmented Generation) approach."""

    def __init__(
        self,
        conversation_state: ConversationState,
        user_state: UserState,
        rag_approach: ChatReadRetrieveReadApproach,
    ):
        if conversation_state is None:
            raise TypeError("[RagBot] conversation_state is required.")
        if rag_approach is None:
            raise TypeError("[RagBot] rag_approach is required.")

        self.conversation_state = conversation_state
        self.user_state = user_state
        self.rag_approach = rag_approach
        self.conversation_history_accessor = conversation_state.create_property(
            "ConversationHistory"
        )

        # Rate‐limit controls
        self._openai_semaphore = asyncio.Semaphore(1)  # serialize OAI calls
        self._max_retries = 3                          # retry attempts on 429
        self._base_retry_delay = 60                    # fallback Retry-After in seconds

        logger.info("[RagBot] Initialised.")

    # ------------------------------------------------------
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
                        "Welcome! I'm a parenting bot. Ask me a question."
                    )
                )

    async def on_message_activity(self, turn_context: TurnContext):
        if (
            turn_context.activity.type != ActivityTypes.message
            or not turn_context.activity.text
        ):
            await turn_context.send_activity(
                MessageFactory.text(
                    f"Unhandled activity type: {turn_context.activity.type}"
                )
            )
            return

        user_message = turn_context.activity.text
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        history = await self.conversation_history_accessor.get(
            turn_context, lambda: []
        )
        messages_for_rag = history + [{"role": "user", "content": user_message}]

        full_response = ""
        extra_info = None
        error_occurred = False
        generic_error_text = "Sorry, I couldn't process your request right now."

        # --- Wrapped Azure OpenAI call with semaphore + retry/back‑off ---
        async with self._openai_semaphore:
            for attempt in range(1, self._max_retries + 1):
                try:
                    extra_info, stream_coro = await self.rag_approach.run_until_final_call(
                        messages_for_rag,
                        overrides={},
                        auth_claims={},
                        should_stream=True,
                    )
                    break  # success
                except RateLimitError as e:
                    # parse Retry-After header if present
                    retry_after = self._base_retry_delay
                    hdrs = getattr(e, "headers", {}) or {}
                    if "Retry-After" in hdrs:
                        try:
                            retry_after = int(hdrs["Retry-After"])
                        except ValueError:
                            pass

                    if attempt < self._max_retries:
                        logger.warning(
                            "Rate limit hit (attempt %s/%s). Sleeping %ss...",
                            attempt, self._max_retries, retry_after
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        # final failure
                        logger.error("Exceeded max retries for rate limit.")
                        await turn_context.send_activity(
                            MessageFactory.text(
                                "I'm still overloaded by too many requests. Please try again in a minute."
                            )
                        )
                        return

        # If we have a valid stream_coro, proceed to stream the response
        try:
            stream = await stream_coro
            async for update in stream:
                chunk = update.choices[0].delta.content or ""
                if chunk:
                    full_response += chunk
                    await turn_context.send_activity(
                        MessageFactory.text(chunk)
                    )
            logger.info("[RagBot] Answer length: %s", len(full_response))

        # ---------- existing Azure SDK error capture ----------
        except HttpResponseError as http_err:
            error_occurred = True
            hdrs: Dict[str, str] = {}
            if getattr(http_err, "response", None) and http_err.response.headers:
                hdrs = dict(http_err.response.headers)
            logger.error("Headers returned on error: %s", hdrs)
            traceback.print_exc()

            status_code = getattr(http_err, "status_code", None) or (
                http_err.response.status_code if http_err.response else "Unknown"
            )
            headers_lower = {k.lower(): v for k, v in hdrs.items()}
            request_id = (
                headers_lower.get("x-ms-azure-search-requestid")
                or headers_lower.get("x-ms-request-id")
                or headers_lower.get("request-id")
                or "N/A"
            )
            logger.error(
                "HttpResponseError | status=%s | request_id=%s | message=%s",
                status_code,
                request_id,
                str(http_err),
            )

            await turn_context.send_activity(
                MessageFactory.text(
                    f"The service returned **{status_code} Forbidden**.\n"
                    f"Request ID: `{request_id}`\n"
                    "Please verify credentials, RBAC or network settings and try again."
                )
            )

        except Exception as ex:
            error_occurred = True
            traceback.print_exc()
            logger.exception("Unexpected error: %s", ex)
            await turn_context.send_activity(
                MessageFactory.text(generic_error_text)
            )

        # fallback if nothing streamed
        if not error_occurred and not full_response:
            await turn_context.send_activity(
                MessageFactory.text(
                    "Sorry, I didn't get a response. Could you please rephrase?"
                )
            )

        # show source links
        if extra_info and getattr(extra_info, "source_documents", None):
            links = []
            for doc in extra_info.source_documents:
                url = getattr(doc, "metadata", {}).get("source")
                if url and url not in links:
                    links.append(url)
            if links:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Source links:\n" + "\n".join(f"- {u}" for u in links)
                    )
                )

        # store history
        if not error_occurred and full_response:
            history.append({"role": "assistant", "content": full_response})
            await self.conversation_history_accessor.set(
                turn_context, history[-10:]
            )
