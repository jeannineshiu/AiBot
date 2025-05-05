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
        # 1. Read the original prompt content
        raw = (self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8")
        # 2. Remove markdown image syntax referencing local files
        cleaned = re.sub(r'!\[.*?\]\(/fileadmin/[^)]+\)', '', raw)
        # 3. Remove front-matter tools definition
        cleaned = re.sub(r'(?m)^tools:.*\n?', '', cleaned)
        # 4. Remove any other /fileadmin references
        cleaned = re.sub(r'/fileadmin/[^\)\]\s"\'#]+', '', cleaned)

        # 5. Load cleaned prompt via a temporary directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_prompt = pathlib.Path(tmp_dir) / path
            temp_prompt.write_text(cleaned, encoding="utf-8")
            # Copy associated tools JSON if present
            tools_name = pathlib.Path(path).stem + "_tools.json"
            src_tools = self.PROMPTS_DIRECTORY / tools_name
            dst_tools = pathlib.Path(tmp_dir) / tools_name
            if src_tools.exists():
                shutil.copy(src_tools, dst_tools)
            # Load the prompt asset without missing file references
            prompt_asset = prompty.load(str(temp_prompt))

        return prompt_asset

    def load_tools(self, path: str):
        return json.loads((self.PROMPTS_DIRECTORY / path).read_text(encoding="utf-8"))

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        return prompty.prepare(prompt, data)