class AIModelInterface:
    def detect_language(self, text: str) -> str:
        raise NotImplementedError("langdetect method not implemented")

