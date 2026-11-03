"""上传接口错误语义:输入错误 400,AI 上游/格式错误 502。"""

import io
import json
import shutil
from pathlib import Path

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api.v1.endpoints import upload as upload_module
from app.main import ai_provider_error_handler
from app.services.ai_provider import (
    AIProviderError,
    AIProviderUnavailableError,
    AIResponseFormatError,
)


def _upload(filename: str = "paper.pdf") -> UploadFile:
    return UploadFile(io.BytesIO(b"%PDF-1.4\n%fake\n"), filename=filename)


async def _invoke(monkeypatch, *, error=None, filename="paper.pdf"):
    created: list[Path] = []

    async def fake_process(file_path, db, **kwargs):
        created.append(Path(file_path).parent)
        if error is not None:
            raise error
        return {"task_id": "t", "content": "", "questions": [], "paper": None}

    monkeypatch.setattr(upload_module.pdf_processor, "process_pdf", fake_process)
    try:
        await upload_module.upload_pdf(
            db=None, file=_upload(filename), mode="extract", method="ai", subject_id=1
        )
    except HTTPException as exc:
        return exc
    except AIProviderError as exc:
        # 端点把 AI 错误原样抛给全局异常处理器(502)。
        response = await ai_provider_error_handler(None, exc)
        return SimpleNamespace(
            status_code=response.status_code,
            detail=json.loads(response.body)["detail"],
        )
    finally:
        for directory in created:
            shutil.rmtree(directory, ignore_errors=True)
    return None


async def test_ai_response_format_error_returns_502(monkeypatch):
    exc = await _invoke(monkeypatch, error=AIResponseFormatError("bad json"))
    assert exc is not None
    assert exc.status_code == 502
    assert "格式" in exc.detail


async def test_ai_unavailable_error_returns_502(monkeypatch):
    exc = await _invoke(
        monkeypatch,
        error=AIProviderUnavailableError("AI 服务域名解析失败（DNS），请检查网络后重试"),
    )
    assert exc is not None
    assert exc.status_code == 502
    assert "DNS" in exc.detail


async def test_user_input_value_error_still_returns_400(monkeypatch):
    exc = await _invoke(monkeypatch, error=ValueError("扫描版 PDF 需要 AI 视觉模型支持"))
    assert exc is not None
    assert exc.status_code == 400
    assert "视觉模型" in exc.detail


async def test_non_pdf_filename_returns_400(monkeypatch):
    exc = await _invoke(monkeypatch, filename="paper.txt")
    assert exc is not None
    assert exc.status_code == 400


async def test_global_handler_maps_ai_errors_to_502_without_leaking_details():
    response = await ai_provider_error_handler(None, AIResponseFormatError("secret=abc"))
    assert response.status_code == 502
    body = json.loads(response.body)
    assert "secret=abc" not in body["detail"]
    assert "格式" in body["detail"]

    response = await ai_provider_error_handler(
        None, AIProviderUnavailableError("AI 服务连接失败（网络），请稍后重试")
    )
    assert response.status_code == 502
    assert "网络" in json.loads(response.body)["detail"]


def test_ai_errors_are_not_value_errors():
    # 避免再次被 upload 的 `except ValueError -> 400` 误吞。
    assert not issubclass(AIResponseFormatError, ValueError)
    assert not issubclass(AIProviderUnavailableError, ValueError)
