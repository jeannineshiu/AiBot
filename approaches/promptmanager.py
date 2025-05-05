import json
import pathlib
import re
import tempfile

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

        # 2. Remove markdown image syntax that references local /fileadmin paths
        cleaned = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', raw)

        # 3. Remove HTML <img> tags pointing to /fileadmin
        cleaned = re.sub(r'<img[^>]+src=["\']/fileadmin/[^"\']+["\'][^>]*>', '', cleaned)

        # 4. Remove front-matter tools definitions to avoid missing JSON files
        cleaned = re.sub(r'(?m)^tools:.*\n?', '', cleaned)

        # 5. Write cleaned prompt into a temporary directory for Prompty to load
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_prompt_path_obj = pathlib.Path(tmp_dir) / path
            temp_prompt_path_obj.parent.mkdir(parents=True, exist_ok=True)
            temp_prompt_path_obj.write_text(cleaned, encoding="utf-8")
            prompt_asset = prompty.load(str(temp_prompt_path_obj))

        if prompt_asset is None:
            raise RuntimeError(f"Failed to load prompt asset from {path} after cleaning.")

        return prompt_asset

    def load_tools(self, path: str):
        tool_path = self.PROMPTS_DIRECTORY / path
        if not tool_path.exists():
            raise FileNotFoundError(f"Tool definition file not found at {tool_path}")
        try:
            return json.loads(tool_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {tool_path}: {e}") from e

    def _strip_fileadmin_images(self, text: str) -> str:
        # Remove Markdown images like ![text](/fileadmin/...)
        text = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', text)
        # Remove HTML <img> tags with src="/fileadmin/..."
        text = re.sub(r'<img[^>]+src=["\']/fileadmin/[^"\']+["\'][^>]*>', '', text)
        # Optionally remove raw /fileadmin/... URLs
        text = re.sub(r'/fileadmin/\S+', '', text)
        return text

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        try:
            # Clean image references from all text_sources
            if "text_sources" in data and isinstance(data["text_sources"], list):
                cleaned_sources = []
                for src in data["text_sources"]:
                    if isinstance(src, str):
                        cleaned_sources.append(self._strip_fileadmin_images(src))
                    else:
                        cleaned_sources.append(src)
                data["text_sources"] = cleaned_sources

            return prompty.prepare(prompt, data)
        except Exception as e:
            print(f"Error rendering prompt with data: {data}")
            raise RuntimeError(f"Failed during prompty.prepare: {e}") from e
