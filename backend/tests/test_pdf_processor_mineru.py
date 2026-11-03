"""PdfProcessor 的 MinerU 分支:成功走 markdown 管线、错误分级回退策略、默认关闭。

HTTP 与摄取全部打桩(mock),只验证接线与回退语义;不触网、不写正式数据库。
"""

import uuid

import pymupdf
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import pdf_processor as pdf_processor_module
from app.services.importing.mineru_ingest import (
    MinerUAuthError,
    MinerUConfigError,
    MinerUParseError,
    MinerURequestError,
    MinerUServiceError,
    MinerUTransportError,
    mineru_ingestor,
)
from app.services.pdf_processor import pdf_processor

TAG_TEXT = (
    "【题目】下列关于集合的说法正确的是\n"
    "【题型】单选\n"
    "【选项】A. 空集是任何集合的子集  B. 0 是空集  C. {0} 是空集  D. 以上都不对\n"
    "【答案】A\n"
    "\n"
    "【题目】1 + 1 = ____\n"
    "【题型】填空\n"
    "【答案】2\n"
)

MINERU_MD = (
    "【题目】MinerU 解析出来的题\n"
    "【题型】单选\n"
    "【选项】A. 甲  B. 乙\n"
    "【答案】A"
)


def _make_text_pdf(path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11, fontname="china-s")
    doc.save(path)
    doc.close()


def _pdf(tmp_path, text: str = TAG_TEXT):
    path = tmp_path / f"{uuid.uuid4().hex[:8]}.pdf"
    _make_text_pdf(path, text)
    return path


@pytest.fixture
def mineru_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MINERU_ENABLED", True)
    monkeypatch.setattr(settings, "MINERU_FALLBACK", True)
    monkeypatch.setattr(settings, "MINERU_API_KEY", SecretStr("unit-test-key"))
    monkeypatch.setattr(settings, "MINERU_TIER", "standard")


def _forbid_legacy(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("不应走旧 PDF 解析路径")

    monkeypatch.setattr(pdf_processor_module, "extract_pdf_text", _boom)
    monkeypatch.setattr(pdf_processor_module, "extract_pdf_markdown", _boom)
    monkeypatch.setattr(pdf_processor_module, "render_pdf_pages", _boom)


def _return(markdown, meta):
    async def _ingest(file_path, *, task_id):
        return markdown, meta

    return _ingest


def _raise(error):
    async def _ingest(file_path, *, task_id):
        raise error

    return _ingest


def test_mineru_error_hierarchy_maps_to_400():
    from app.services.importing.mineru_ingest import MinerUError

    for cls in (
        MinerUError,
        MinerUConfigError,
        MinerUAuthError,
        MinerURequestError,
        MinerUTransportError,
        MinerUServiceError,
        MinerUParseError,
    ):
        assert issubclass(cls, ValueError)


async def test_success_routes_to_markdown_pipeline_with_parse_meta(
    tmp_path, db_session, monkeypatch, mineru_enabled
):
    _forbid_legacy(monkeypatch)
    meta = {
        "engine": "mineru",
        "tier": "standard",
        "elapsed_ms": 42,
        "images": 0,
        "html_tables": 0,
        "warnings": [],
    }
    monkeypatch.setattr(mineru_ingestor, "ingest", _return(MINERU_MD, meta))

    result = await pdf_processor.process_pdf(
        _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
    )

    assert result["parse_meta"]["engine"] == "mineru"
    assert result["parse_meta"]["tier"] == "standard"
    assert "parse_seconds" in result["parse_meta"]
    assert len(result["questions"]) == 1
    assert "MinerU 解析出来的题" in result["questions"][0]["content"]
    assert result["content"] == MINERU_MD


async def test_fallbackable_error_uses_legacy_when_fallback_enabled(
    tmp_path, db_session, monkeypatch, mineru_enabled
):
    monkeypatch.setattr(mineru_ingestor, "ingest", _raise(MinerUServiceError("HTTP 500")))

    result = await pdf_processor.process_pdf(
        _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
    )

    assert len(result["questions"]) == 2
    assert "parse_meta" not in result


async def test_parse_error_falls_back_when_fallback_enabled(
    tmp_path, db_session, monkeypatch, mineru_enabled
):
    monkeypatch.setattr(
        mineru_ingestor, "ingest", _raise(MinerUParseError("MinerU 返回的 Markdown 为空"))
    )

    result = await pdf_processor.process_pdf(
        _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
    )

    assert len(result["questions"]) == 2
    assert "parse_meta" not in result


async def test_fallback_disabled_propagates_error(
    tmp_path, db_session, monkeypatch, mineru_enabled
):
    monkeypatch.setattr(settings, "MINERU_FALLBACK", False)
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(
        mineru_ingestor, "ingest", _raise(MinerUTransportError("无法连接 MinerU 服务"))
    )

    with pytest.raises(MinerUTransportError):
        await pdf_processor.process_pdf(
            _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
        )


@pytest.mark.parametrize(
    "error",
    [
        MinerUAuthError("MinerU 认证失败(HTTP 401)"),
        MinerUConfigError("未配置 MINERU_API_KEY"),
        MinerURequestError("MinerU 拒绝请求(HTTP 422)"),
    ],
)
async def test_config_auth_request_errors_never_fall_back(
    tmp_path, db_session, monkeypatch, mineru_enabled, error
):
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(mineru_ingestor, "ingest", _raise(error))

    with pytest.raises(type(error)):
        await pdf_processor.process_pdf(
            _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
        )


async def test_disabled_by_default_skips_mineru(tmp_path, db_session, monkeypatch):
    async def _boom(file_path, *, task_id):
        raise AssertionError("MINERU_ENABLED=False 时不应调用 MinerU")

    monkeypatch.setattr(mineru_ingestor, "ingest", _boom)
    assert settings.MINERU_ENABLED is False

    result = await pdf_processor.process_pdf(
        _pdf(tmp_path), db_session, filename="paper.pdf", method="structured"
    )

    assert len(result["questions"]) == 2
    assert "parse_meta" not in result

async def test_mineru_fallback_failure_mentions_mineru(
    tmp_path, db_session, monkeypatch, mineru_enabled
):
    """MinerU 不可用并回退后,若旧流程也失败,错误信息应带上前因。"""
    import pymupdf

    monkeypatch.setattr(
        mineru_ingestor, "ingest", _raise(MinerUTransportError("无法连接 MinerU 服务"))
    )
    pdf = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0, 0, 0))
    doc.save(pdf)
    doc.close()

    with pytest.raises(ValueError, match="MinerU 不可用（transport）") as excinfo:
        await pdf_processor.process_pdf(
            pdf, db_session, filename="scanned.pdf", method="structured"
        )
    assert "视觉模型" in str(excinfo.value)
