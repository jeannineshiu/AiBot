import json
import pathlib
import re
import tempfile
import shutil

# Removed the import and monkey-patch for prompty.parsers here
# as it was causing the AttributeError and the cleaning below should suffice.
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
        # This cleaning step prevents prompty from seeing these paths
        cleaned = re.sub(r'!\[[^\]]*\]\(/fileadmin/[^)]*\)', '', raw)

        # 3. Strip out any remaining /fileadmin paths
        # This is a broader cleanup for the same purpose
        cleaned = re.sub(r'/fileadmin/\S+', '', cleaned)

        # 4. Remove front-matter tools definitions to avoid missing JSON files
        cleaned = re.sub(r'(?m)^tools:.*\n?', '', cleaned)

        # 5. Write cleaned prompt into a temporary directory for Prompty to load
        temp_prompt_path = None # Define outside 'with' for potential use after block (though not used here currently)
        prompt_asset = None
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Ensure parent directory exists if path includes subdirs (though less likely here)
            temp_prompt_path_obj = pathlib.Path(tmp_dir) / path
            temp_prompt_path_obj.parent.mkdir(parents=True, exist_ok=True) # Ensure parent dir exists
            temp_prompt_path_obj.write_text(cleaned, encoding="utf-8")
            temp_prompt_path = str(temp_prompt_path_obj) # Store path as string for prompty.load

            # Copy associated tools JSON if it exists
            tools_name = pathlib.Path(path).stem + "_tools.json"
            src_tools = self.PROMPTS_DIRECTORY / tools_name
            dst_tools = pathlib.Path(tmp_dir) / tools_name
            if src_tools.exists():
                shutil.copy(src_tools, dst_tools)

            # Load the prompt asset using the cleaned content from the temporary file
            # Ensure the path passed to prompty.load exists
            if pathlib.Path(temp_prompt_path).exists():
                prompt_asset = prompty.load(temp_prompt_path)
            else:
                # Handle case where temp file writing might fail silently or path is wrong
                # (Though unlikely with TemporaryDirectory unless 'path' variable is unusual)
                raise FileNotFoundError(f"Temporary prompt file not found at {temp_prompt_path}")


        # Ensure prompt_asset was loaded successfully before returning
        if prompt_asset is None:
             raise RuntimeError(f"Failed to load prompt asset from {path} after cleaning.")

        return prompt_asset

    def load_tools(self, path: str):
        # Load tool definitions from a JSON file
        tool_path = self.PROMPTS_DIRECTORY / path
        if not tool_path.exists():
            raise FileNotFoundError(f"Tool definition file not found at {tool_path}")
        try:
            return json.loads(tool_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {tool_path}: {e}") from e


    def render_prompt(self, prompt, data) -> list[ChatCompletionMessageParam]:
        # Prepare and render the prompt with the provided data
        try:
            return prompty.prepare(prompt, data)
        except Exception as e:
            # Add more context if rendering fails
            print(f"Error rendering prompt with data: {data}")
            raise RuntimeError(f"Failed during prompty.prepare: {e}") from e