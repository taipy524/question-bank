import asyncio
import logging
from typing import Any, Dict, Optional

from app.core.vector_store import VectorStore
from app.services.ai_provider import is_upstream_unavailable
from app.services.embedding import ensure_embedding_function

logger = logging.getLogger(__name__)

# 首次 + 最多 2 次重试;退避很短,避免拖慢整份解析。
RETRIEVAL_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.2, 0.5)
_TRANSIENT_TYPE_NAMES = {
    "ConnectionError", "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "BrokenPipeError", "URLError", "TimeoutError",
}


def _is_transient_error(exc: BaseException) -> bool:
    if is_upstream_unavailable(exc):
        return True
    return any(
        base.__name__ in _TRANSIENT_TYPE_NAMES for base in type(exc).__mro__
    )


class KnowledgePointRetriever:
    """Gates knowledge-point vector search on availability and isolates by subject."""

    @staticmethod
    def available() -> bool:
        return VectorStore.is_available()

    @staticmethod
    async def retrieve(
        query: str, subject_id: Optional[int] = None, limit: int = 5
    ) -> Optional[Dict[str, Any]]:
        """Return ChromaDB results scoped to subject_id, or None when unavailable.

        不可用时先做一次受控重载(带冷却/并发保护),仍不可用才返回 None;
        调用方据此区分"服务不可用"与"没有候选"。
        """
        await ensure_embedding_function()
        if not KnowledgePointRetriever.available():
            return None
        for attempt in range(RETRIEVAL_ATTEMPTS):
            try:
                return await asyncio.to_thread(
                    VectorStore.search_similar,
                    query=query,
                    subject_id=subject_id,
                    limit=limit,
                )
            except Exception as exc:
                retryable = _is_transient_error(exc)
                last_attempt = attempt >= RETRIEVAL_ATTEMPTS - 1
                if not retryable:
                    raise
                if last_attempt:
                    # 重试耗尽:返回 None,由调用方留下 knowledge_points_unavailable 告警。
                    logger.warning(
                        "knowledge point retrieval failed after %s attempts: %s",
                        RETRIEVAL_ATTEMPTS,
                        type(exc).__name__,
                    )
                    return None
                logger.warning(
                    "knowledge point retrieval attempt %s failed (%s), retrying",
                    attempt + 1,
                    type(exc).__name__,
                )
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
        return None
