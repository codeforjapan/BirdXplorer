import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

FASTTEXT_MODEL_PATH = os.getenv("FASTTEXT_MODEL_PATH", "/app/lid.176.ftz")
FASTTEXT_THRESHOLD = float(os.getenv("FASTTEXT_THRESHOLD", "0.7"))

_model = None


def _get_model():  # type: ignore[no-untyped-def]
    global _model
    if _model is None:
        import fasttext  # type: ignore[import-untyped]

        _model = fasttext.load_model(FASTTEXT_MODEL_PATH)
    return _model


def detect_language_fasttext(text: str, threshold: float = FASTTEXT_THRESHOLD) -> Optional[str]:
    """
    fasttext で言語判定を行い、confidence >= threshold の場合に言語コードを返す。
    threshold 未満またはエラー時は None を返し、呼び出し元で OpenAI fallback を行う。
    """
    try:
        model = _get_model()
        cleaned = text.replace("\n", " ").strip()
        if not cleaned:
            return None
        labels, probs = model.predict(cleaned, k=1)
        lang: str = labels[0].replace("__label__", "")
        confidence = float(probs[0])
        logger.info(f"[FASTTEXT] lang={lang}, confidence={confidence:.3f}, threshold={threshold}")
        if confidence >= threshold:
            return lang
        logger.info(f"[FASTTEXT_FALLBACK] confidence {confidence:.3f} < {threshold}, delegating to OpenAI")
        return None
    except Exception as e:
        logger.warning(f"[FASTTEXT_ERROR] {e}, falling back to OpenAI")
        return None
