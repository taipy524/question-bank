"""Embedding 初始化恢复、知识点检索可用性区分与 ID 映射测试。

不访问真实 MySQL/Chroma/AI:全部通过 monkeypatch 模拟。
"""

import asyncio

import pytest

import app.services.embedding as embedding_module
from app.core.vector_store import VectorStore
from app.schemas.ai import AIQuestion
from app.services.importing.enrich import KnowledgePointEnricher
from app.services.kp_retriever import KnowledgePointRetriever


@pytest.fixture(autouse=True)
def _reset_recovery_state(monkeypatch):
    monkeypatch.setattr(embedding_module, "_last_ensure_attempt", 0.0)
    monkeypatch.setattr(embedding_module, "_reload_in_progress", False)


def _patch_availability(monkeypatch, state: dict) -> None:
    monkeypatch.setattr(
        VectorStore, "is_available", classmethod(lambda cls: bool(state["ok"]))
    )


async def test_ensure_recovers_after_successful_reload(monkeypatch):
    state = {"ok": False}
    calls = []
    _patch_availability(monkeypatch, state)

    async def fake_reload():
        calls.append(1)
        state["ok"] = True

    monkeypatch.setattr(embedding_module, "reload_embedding_function", fake_reload)

    assert await embedding_module.ensure_embedding_function() is True
    assert len(calls) == 1


async def test_ensure_retry_is_throttled_by_cooldown(monkeypatch):
    state = {"ok": False}
    calls = []
    _patch_availability(monkeypatch, state)

    async def fake_reload():
        calls.append(1)  # 仍然失败

    monkeypatch.setattr(embedding_module, "reload_embedding_function", fake_reload)

    assert await embedding_module.ensure_embedding_function() is False
    assert await embedding_module.ensure_embedding_function() is False
    assert len(calls) == 1, "冷却窗口内不应重复重载"


async def test_concurrent_ensure_runs_single_reload(monkeypatch):
    state = {"ok": False}
    calls = []
    _patch_availability(monkeypatch, state)

    async def slow_reload():
        calls.append(1)
        await asyncio.sleep(0.02)

    monkeypatch.setattr(embedding_module, "reload_embedding_function", slow_reload)

    results = await asyncio.gather(
        *[embedding_module.ensure_embedding_function() for _ in range(5)]
    )

    assert len(calls) == 1, "并发调用只应触发一次重载"
    assert all(result is False for result in results)


async def test_init_retry_succeeds_on_third_attempt(monkeypatch):
    state = {"ok": False}
    attempts = []
    _patch_availability(monkeypatch, state)

    async def fake_reload():
        attempts.append(1)
        if len(attempts) >= 3:
            state["ok"] = True

    monkeypatch.setattr(embedding_module, "reload_embedding_function", fake_reload)

    assert (
        await embedding_module.init_embedding_with_retry(attempts=3, base_delay=0)
        is True
    )
    assert len(attempts) == 3


async def test_init_retry_exhausted_returns_false(monkeypatch):
    state = {"ok": False}
    attempts = []
    _patch_availability(monkeypatch, state)

    async def fake_reload():
        attempts.append(1)

    monkeypatch.setattr(embedding_module, "reload_embedding_function", fake_reload)

    assert (
        await embedding_module.init_embedding_with_retry(attempts=2, base_delay=0)
        is False
    )
    assert len(attempts) == 2


async def test_retriever_attempts_recovery_then_returns_none(monkeypatch):
    state = {"ok": False}
    calls = []
    _patch_availability(monkeypatch, state)

    async def fake_ensure():
        calls.append(1)
        return False

    monkeypatch.setattr("app.services.kp_retriever.ensure_embedding_function", fake_ensure)

    assert await KnowledgePointRetriever.retrieve("二次函数") is None
    assert calls == [1]


class _RerankProvider:
    def __init__(self, mapping):
        self._mapping = mapping
        self.items = None

    async def batch_rerank_knowledge_points(self, items, config=None):
        self.items = items
        return self._mapping


async def test_enrich_warns_when_retrieval_unavailable(monkeypatch):
    async def fake_retrieve(query, subject_id=None, limit=5):
        return None

    monkeypatch.setattr(KnowledgePointRetriever, "retrieve", fake_retrieve)
    question = AIQuestion(q_type="single_choice", content="题干", options=["A. 1"])

    warnings = await KnowledgePointEnricher().enrich(
        [question], subject_id=1, provider=_RerankProvider({}), config={}
    )

    assert warnings == ["knowledge_points_unavailable"]
    assert not question.knowledge_point_ids
    assert question.knowledge_points is None, "不可用时不得伪造匹配结果"


async def test_enrich_maps_reranked_candidates_to_ids(monkeypatch):
    async def fake_retrieve(query, subject_id=None, limit=5):
        return {
            "documents": [["二次函数", "概率初步"]],
            "ids": [["11", "22"]],
            "distances": [[0.1, 0.2]],
        }

    monkeypatch.setattr(KnowledgePointRetriever, "retrieve", fake_retrieve)
    provider = _RerankProvider({"0": ["概率初步"]})
    question = AIQuestion(q_type="single_choice", content="题干")

    warnings = await KnowledgePointEnricher().enrich(
        [question], subject_id=1, provider=provider, config={}
    )

    assert warnings == []
    assert question.knowledge_points == ["概率初步"]
    assert question.knowledge_point_ids == [22]
    assert provider.items and provider.items[0]["id"] == "0"


async def test_enrich_without_candidates_is_not_a_warning(monkeypatch):
    async def fake_retrieve(query, subject_id=None, limit=5):
        return {"documents": [[]], "ids": [[]], "distances": [[]]}

    monkeypatch.setattr(KnowledgePointRetriever, "retrieve", fake_retrieve)
    question = AIQuestion(q_type="single_choice", content="题干")

    warnings = await KnowledgePointEnricher().enrich(
        [question], subject_id=1, provider=_RerankProvider({}), config={}
    )

    assert warnings == []
    assert not question.knowledge_point_ids


async def test_enrich_search_exception_is_reported_as_unavailable(monkeypatch):
    async def boom(query, subject_id=None, limit=5):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(KnowledgePointRetriever, "retrieve", boom)
    question = AIQuestion(q_type="single_choice", content="题干")

    warnings = await KnowledgePointEnricher().enrich(
        [question], subject_id=1, provider=_RerankProvider({}), config={}
    )

    assert warnings == ["knowledge_points_unavailable"]
    assert not question.knowledge_point_ids


import httpx

import app.services.kp_retriever as kp_module


def _patch_retrieval(monkeypatch, search):
    monkeypatch.setattr(
        VectorStore, "is_available", classmethod(lambda cls: True)
    )
    monkeypatch.setattr(
        "app.services.kp_retriever.ensure_embedding_function",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(kp_module, "RETRY_BACKOFF_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(VectorStore, "search_similar", staticmethod(search))


async def test_retrieve_retries_transient_error_then_succeeds(monkeypatch):
    calls = []

    def search(**kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("chroma down")
        return {"documents": [["二次函数"]]}

    _patch_retrieval(monkeypatch, search)

    result = await KnowledgePointRetriever.retrieve("二次函数")

    assert result == {"documents": [["二次函数"]]}
    assert len(calls) == 3, "首次失败后应重试两次"


async def test_retrieve_gives_up_after_two_retries(monkeypatch):
    calls = []

    def search(**kwargs):
        calls.append(1)
        raise ConnectionResetError("chroma reset")

    _patch_retrieval(monkeypatch, search)

    assert await KnowledgePointRetriever.retrieve("二次函数") is None
    assert len(calls) == 3
    assert kp_module.RETRIEVAL_ATTEMPTS == 3


async def test_retrieve_does_not_retry_non_transient_error(monkeypatch):
    calls = []

    def search(**kwargs):
        calls.append(1)
        raise ValueError("bad query")

    _patch_retrieval(monkeypatch, search)

    with pytest.raises(ValueError):
        await KnowledgePointRetriever.retrieve("二次函数")
    assert len(calls) == 1, "非瞬时错误不应重试"
