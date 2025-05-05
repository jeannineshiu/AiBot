import json
import pathlib
import re
import tempfile
import shutil

import prompty
# Monkey-patch to disable inline image loading (avoid FileNotFoundError on local paths)
import prompty.parsers
prompty.parsers.Parser.inline_image = lambda self, image_path: {"url": ""}
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
        # 1. Read the original prompt content
        raw = (self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8")

        # 2. Remove markdown image syntax that references local /fileadmin paths
        cleaned = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', raw)

        # 3. Strip out any remaining /fileadmin paths
        cleaned = re.sub(r'/fileadmin/\S+', '', cleaned)

        # 4. Remove front-matter tools definitions to avoid missing JSON files
        cleaned = re.sub(r'(?m)^tools:.*\n?', '', cleaned)

        # 5. Write cleaned prompt into a temporary directory for Prompty to load
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_prompt_path = pathlib.Path(tmp_dir) / path
            temp_prompt_path.write_text(cleaned, encoding="utf-8")

            # Copy associated tools JSON if it exists
            tools_name = pathlib.Path(path).stem + "_tools.json"
            src_tools = self.PROMPTS_DIRECTORY / tools_name
            dst_tools = pathlib.Path(tmp_dir) / tools_name
            if src_tools.exists():
                shutil.copy(src_tools, dst_tools)

            # Load the prompt asset without any local file references
            prompt_asset = prompty.load(str(temp_prompt_path))

        return prompt_asset

    def load_tools(self, path: str):
        # Load tool definitions from a JSON file
        return json.loads((self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8"))

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        # Prepare and render the prompt with the provided data
        return prompty.prepare(prompt, data)
