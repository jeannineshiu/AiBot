import json
import pathlib
import re

import prompty
from openai.types.chat import ChatCompletionMessageParam


class PromptManager:
    def load_prompt(self, path: str):
        raise NotImplementedError

    def load_tools(self, path: str):
        raise NotImplementedError

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        raise NotImplementedError


class PromptyManager(PromptManager):

    PROMPTS_DIRECTORY = pathlib.Path(__file__).parent / "prompts"

    def load_prompt(self, path: str):
        # 1. Read the original Markdown content
        raw = (self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8")
        # 2. Remove all local filesystem image references using a regex
        cleaned = re.sub(r'!\[.*?\]\(/fileadmin/[^\)]+\)', '', raw)
        # 3. Pass the cleaned string to prompty
        #    Assuming prompty supports loading from a string, typically called load_string or loads
        return prompty.load_string(cleaned)

    def load_tools(self, path: str):
        # Load tool definitions from a JSON file
        return json.loads((self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8"))

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        # Prepare and render the prompt with the provided data
        return prompty.prepare(prompt, data)
