import json
import pathlib
import re
import tempfile
import shutil  # For file copying

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
        original_prompt_full_path = self.PROMPTS_DIRECTORY / path
        if not original_prompt_full_path.exists():
            raise FileNotFoundError(f"Original prompt file not found at {original_prompt_full_path}")

        # 1. Read the original prompt content
        raw_content = original_prompt_full_path.read_text(encoding="utf-8")

        # 2. Clean /fileadmin/ image links from the prompt body
        content_for_temp_file = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', raw_content)
        content_for_temp_file = re.sub(r'<img[^>]+src=["\']/fileadmin/[^"\']+["\'][^>]*>', '', content_for_temp_file)

        # 3. Write cleaned prompt into a temporary directory for Prompty to load
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_path = pathlib.Path(tmp_dir_name)

            # Replicate any subdirectory structure
            temp_prompt_path_obj = tmp_path / path
            temp_prompt_path_obj.parent.mkdir(parents=True, exist_ok=True)
            temp_prompt_path_obj.write_text(content_for_temp_file, encoding="utf-8")

            # 4. Always copy the known tools JSON into the temp directory
            tools_src = self.PROMPTS_DIRECTORY / "chat_query_rewrite_tools.json"
            tools_dst = tmp_path / "chat_query_rewrite_tools.json"
            if tools_src.exists():
                shutil.copy(tools_src, tools_dst)

            # 5. Load the prompt (Prompty will find the JSON alongside)
            prompt_asset = prompty.load(str(temp_prompt_path_obj))

        if prompt_asset is None:
            raise RuntimeError(f"Failed to load prompt asset from {path} after processing.")

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
        text = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', text)
        text = re.sub(r'<img[^>]+src=["\']/fileadmin/[^"\']+["\'][^>]*>', '', text)
        text = re.sub(r'/fileadmin/\S+', '', text)
        return text

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        try:
            if "text_sources" in data and isinstance(data["text_sources"], list):
                cleaned_sources = []
                for src_item in data["text_sources"]:
                    if isinstance(src_item, str):
                        cleaned_sources.append(self._strip_fileadmin_images(src_item))
                    else:
                        cleaned_sources.append(src_item)
                data["text_sources"] = cleaned_sources

            return prompty.prepare(prompt, data)
        except Exception as e:
            print(f"Error rendering prompt. Data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            raise RuntimeError(f"Failed during prompty.prepare: {e}") from e
