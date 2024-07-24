class AIModelInterface:
    def detect_language(self, text: str) -> str:
        raise NotImplementedError("detect_language method not implemented")

