from typing import Dict, List


class AIModelInterface:
    def detect_language(self, text: str) -> str:
        raise NotImplementedError("detect_language method not implemented")

    def detect_topic(self, note_id: int, note: str) -> Dict[str, List[str]]:
        raise NotImplementedError("detect_topic method not implemented")
