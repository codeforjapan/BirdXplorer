from birdxplorer_etl.lib.ai_model.ai_model_interface_base import AIModelInterface
from birdxplorer_etl.settings import CLAUDE_TOKEN


class ClaudeService(AIModelInterface):
    def __init__(self):
        self.api_key = CLAUDE_TOKEN
