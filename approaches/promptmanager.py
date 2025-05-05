import json
import pathlib
import re
import tempfile
import shutil

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
        # 2. Remove any local filesystem image references
        cleaned = re.sub(r'!\[.*?\]\(/fileadmin/[^\)]+\)', '', raw)
        # 3. Strip out any front-matter tools file reference to avoid missing dependencies
        cleaned = re.sub(r'(?m)^tools:.*\n?', '', cleaned)

        # 4. Use a temporary directory to isolate prompt loading
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Write cleaned prompt markdown to temp file
            temp_prompt_path = pathlib.Path(tmp_dir) / path
            temp_prompt_path.write_text(cleaned, encoding="utf-8")

            # Copy associated tools JSON if present
            tools_name = pathlib.Path(path).stem + "_tools.json"
            src_tools = self.PROMPTS_DIRECTORY / tools_name
            dst_tools = pathlib.Path(tmp_dir) / tools_name
            if src_tools.exists():
                shutil.copy(src_tools, dst_tools)

            # Load the prompt asset; missing tools references are now removed
            prompt_asset = prompty.load(str(temp_prompt_path))

        return prompt_asset

    def load_tools(self, path: str):
        # Load tool definitions from a JSON file
        return json.loads((self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8"))

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        # Prepare and render the prompt with the provided data
        return prompty.prepare(prompt, data)
