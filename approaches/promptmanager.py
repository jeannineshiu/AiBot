import json
import pathlib
import re
import tempfile
import os

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
        # 3. Write the cleaned content to a temporary file for Prompty to load
        with tempfile.NamedTemporaryFile(mode="w", suffix=path, delete=False, encoding="utf-8") as tmp_file:
            tmp_file.write(cleaned)
            temp_path = tmp_file.name

        try:
            # Load the prompt asset from the temporary file
            prompt_asset = prompty.load(temp_path)
        finally:
            # Clean up the temporary file
            os.remove(temp_path)

        return prompt_asset

    def load_tools(self, path: str):
        # Load tool definitions from a JSON file
        return json.loads((self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8"))

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        # Prepare and render the prompt with the provided data
        return prompty.prepare(prompt, data)
