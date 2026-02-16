"""AI API呼び出し用のリトライハンドラー"""

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger()

T = TypeVar("T")


class AIAPIError(Exception):
    """AI API呼び出しエラー"""

    pass


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    指数バックオフ付きリトライデコレータ

    Args:
        max_retries: 最大リトライ回数
        initial_delay: 初回リトライまでの待機秒数
        backoff_factor: 待機時間の増加係数
        max_delay: 最大待機秒数
        retryable_exceptions: リトライ対象の例外タプル

    Returns:
        デコレータ関数
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            delay = initial_delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(f"[RETRY_EXHAUSTED] All {max_retries} retries failed for {func.__name__}: {e}")
                        raise AIAPIError(f"AI API call failed after {max_retries} retries: {e}") from e

                    logger.warning(
                        f"[RETRY] Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # ここには到達しないはずだが、型チェック用
            raise AIAPIError(f"Unexpected retry state: {last_exception}")

        return wrapper

    return decorator


def call_ai_api_with_retry(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    **kwargs: Any,
) -> T:
    """
    AI API呼び出しをリトライ付きで実行する関数

    Args:
        func: 呼び出す関数
        *args: 関数の位置引数
        max_retries: 最大リトライ回数
        initial_delay: 初回リトライまでの待機秒数
        **kwargs: 関数のキーワード引数

    Returns:
        関数の戻り値

    Raises:
        AIAPIError: 全リトライ失敗時
    """
    last_exception = None
    delay = initial_delay
    backoff_factor = 2.0
    max_delay = 30.0

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e

            if attempt == max_retries:
                logger.error(f"[RETRY_EXHAUSTED] All {max_retries} retries failed: {e}")
                raise AIAPIError(f"AI API call failed after {max_retries} retries: {e}") from e

            logger.warning(f"[RETRY] Attempt {attempt + 1}/{max_retries} failed: {e}. " f"Retrying in {delay:.1f}s...")
            time.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)

    # ここには到達しないはずだが、型チェック用
    raise AIAPIError(f"Unexpected retry state: {last_exception}")
