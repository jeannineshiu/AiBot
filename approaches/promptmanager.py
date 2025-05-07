import json
import pathlib
import re
import tempfile
import shutil # Added for file copying
import yaml   # Added for YAML parsing (front matter). Requires PyYAML installation.

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

        # 2. Clean /fileadmin/ image links from the content that will be written to the temp file.
        # These typically appear in the prompt body, not front matter.
        content_for_temp_file = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', raw_content)
        content_for_temp_file = re.sub(r'<img[^>]+src=["\']/fileadmin/[^"\']+["\'][^>]*>', '', content_for_temp_file)

        # --- New logic to handle tool files referenced in front matter ---
        # We will parse the original raw_content for front matter to ensure clean parsing.
        tool_files_to_copy = []
        try:
            # Split front matter from the rest of the content.
            # Prompty/YAML front matter is typically delimited by '---'.
            # A common pattern is '--- yaml_content --- main_content'.
            if raw_content.startswith("---"):
                parts = raw_content.split("---", 2)
                if len(parts) >= 2: # Found at least one '---' section
                    front_matter_str = parts[1]
                    front_matter_data = yaml.safe_load(front_matter_str)
                    if isinstance(front_matter_data, dict) and "tools" in front_matter_data:
                        tools_val = front_matter_data["tools"]
                        if isinstance(tools_val, str):
                            tool_files_to_copy.append(tools_val)
                        elif isinstance(tools_val, list):
                            for tool_item in tools_val:
                                if isinstance(tool_item, str):
                                    tool_files_to_copy.append(tool_item)
        except yaml.YAMLError as e:
            print(f"Warning: Could not parse YAML front matter from {path}: {e}. Skipping tool file copying.")
        except Exception as e:
            print(f"Warning: Error processing front matter for {path}: {e}. Skipping tool file copying.")
        # --- End of new logic for tool files ---

        # NOTE: Step 4 (Remove front-matter tools definitions) is now REMOVED.
        # We want prompty to process the tools definition, and we'll provide the files.

        # 5. Write cleaned prompt into a temporary directory for Prompty to load
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_path = pathlib.Path(tmp_dir_name)
            
            # 'path' can include subdirectories like "folder/my_prompt.prompty"
            # We need to replicate this structure in the temp directory for prompty.
            temp_prompt_path_obj = tmp_path / path
            temp_prompt_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the content (cleaned of /fileadmin/ images, but with tools definition intact)
            temp_prompt_path_obj.write_text(content_for_temp_file, encoding="utf-8")

            # Copy identified tool files to the temporary directory, maintaining relative paths.
            if tool_files_to_copy:
                original_prompt_parent_dir = original_prompt_full_path.parent
                for tool_file_relative_path_str in tool_files_to_copy:
                    # tool_file_relative_path_str is relative to the .prompty file
                    # e.g., "my_tools.json" or "../common/some_tools.json"
                    original_tool_full_path = (original_prompt_parent_dir / tool_file_relative_path_str).resolve()

                    # Security check: Ensure the resolved path is still within PROMPTS_DIRECTORY
                    # to prevent '..' from escaping the intended base directory.
                    if not str(original_tool_full_path).startswith(str(self.PROMPTS_DIRECTORY.resolve())):
                        print(
                            f"Warning: Tool path '{tool_file_relative_path_str}' in prompt '{path}' "
                            f"resolves to '{original_tool_full_path}', which is outside the "
                            f"allowed prompts directory '{self.PROMPTS_DIRECTORY.resolve()}'. Skipping."
                        )
                        continue
                    
                    if original_tool_full_path.exists() and original_tool_full_path.is_file():
                        # Destination path in temp dir, maintaining the same relative structure
                        # from the temporary .prompty file.
                        temp_tool_destination_path = (temp_prompt_path_obj.parent / tool_file_relative_path_str).resolve()
                        
                        # Ensure the target directory for the tool exists in the temp location
                        temp_tool_destination_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        shutil.copy(original_tool_full_path, temp_tool_destination_path)
                        # print(f"Copied tool '{original_tool_full_path}' to '{temp_tool_destination_path}'") # For debugging
                    else:
                        # This will likely cause prompty.load to fail later, which is expected
                        # if a referenced tool is missing.
                        print(f"Warning: Referenced tool file '{tool_file_relative_path_str}' "
                              f"(resolved to '{original_tool_full_path}') for prompt '{path}' not found. "
                              "Prompty may fail to load tools.")
            
            prompt_asset = prompty.load(str(temp_prompt_path_obj))

        # prompty.load() raises an error if it fails, so prompt_asset should not be None if no error.
        # However, keeping the check for robustness or future prompty versions.
        if prompt_asset is None:
            raise RuntimeError(f"Failed to load prompt asset from {path} after all processing.")

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
        text = re.sub(r'/fileadmin/\S+', '', text) # This was effective for the /fileadmin/ error
        return text

    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        try:
            # Clean image references from all text_sources passed in data
            if "text_sources" in data and isinstance(data["text_sources"], list):
                cleaned_sources = []
                for src_item in data["text_sources"]:
                    if isinstance(src_item, str):
                        cleaned_sources.append(self._strip_fileadmin_images(src_item))
                    else:
                        # If items are not strings (e.g. dicts, other structures), append as-is
                        cleaned_sources.append(src_item)
                data["text_sources"] = cleaned_sources
            
            return prompty.prepare(prompt, data)
        except Exception as e:
            # Consider more specific error logging if needed
            print(f"Error rendering prompt. Data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            raise RuntimeError(f"Failed during prompty.prepare: {e}") from e