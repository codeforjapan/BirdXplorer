from birdxplorer_etl.settings import AI_MODEL
from birdxplorer_etl.lib.openapi.open_ai_service import OpenAIService
from birdxplorer_etl.lib.claude.claude_service import ClaudeService
from birdxplorer_etl.lib.ai_model.ai_model_interface_base import AIModelInterface


def get_ai_service() -> AIModelInterface:
    if AI_MODEL == "openai":
        return OpenAIService()
    elif AI_MODEL == "claude":
        return ClaudeService()
    else:
        raise ValueError(f"Unsupported AI service: {AI_MODEL}")
