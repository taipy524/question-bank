"""MinerU 摄取单测:V1 协议(200/202/轮询/状态码分类)、ZIP 安全、媒体重写与
markdown 归一化。HTTP 全部用 httpx.MockTransport,不触网、不连正式数据库。"""

import hashlib
import io
import uuid
import zipfile

import httpx
import pytest

from app.core.config import settings
from app.services.importing.image_mask import mask_images
from app.services.importing.mineru_ingest import (
    MinerUAuthError,
    MinerUClient,
    MinerUConfigError,
    MinerUIngestor,
    MinerUParseError,
    MinerURequestError,
    MinerUServiceError,
    MinerUTimeoutError,
    MinerUTransportError,
    normalize_mineru_markdown,
)
from app.services.question_content_converter import markdown_to_rich_doc


def _task_id(tag: str) -> str:
    return f"mineru-unit-{tag}-{uuid.uuid4().hex[:8]}"


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _write_pdf(tmp_path) -> "object":
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake\n")
    return path


def _ingest(handler, **client_kwargs) -> MinerUIngestor:
    client_kwargs.setdefault("base_url", "http://mineru.test:8000")
    client_kwargs.setdefault("api_key", "SUPERSECRETKEY")
    client_kwargs.setdefault("poll_interval", 0.01)
    return MinerUIngestor(
        client=MinerUClient(
            transport=httpx.MockTransport(handler), **client_kwargs
        )
    )


def _collect_kinds(node, kinds: set) -> None:
    if isinstance(node, dict):
        if "type" in node:
            kinds.add(node["type"])
        for value in node.values():
            _collect_kinds(value, kinds)
    elif isinstance(node, list):
        for value in node:
            _collect_kinds(value, kinds)


# --------------------------------------------------------------------------- #
# 请求参数 / 认证 / 状态码分类
# --------------------------------------------------------------------------- #


async def test_submit_sends_expected_params_auth_and_raw_body(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"markdown.md": "正文"})
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["content_length"] = request.headers.get("Content-Length")
        seen["params"] = request.url.params
        seen["body"] = request.content
        return httpx.Response(200, content=payload, request=request)

    markdown, meta = await _ingest(handler, tier="standard", timeout_seconds=600).ingest(
        pdf, task_id=_task_id("params")
    )

    assert seen["path"] == "/v1/file_parse"
    assert seen["auth"] == "Bearer SUPERSECRETKEY"
    # 实测服务端只接受 raw 上传承载 filename/sha256sum,multipart 会被 400 拒绝。
    assert seen["content_type"] == "application/octet-stream"
    assert seen["content_length"] == str(len(pdf.read_bytes()))
    assert seen["body"].startswith(b"%PDF")
    params = seen["params"]
    assert params["response_format"] == "zip"
    assert params["tier"] == "standard"
    assert params["wait_timeout"] == "600"
    assert params["ocr_mode"] == "auto"
    assert params["filename"] == "paper.pdf"
    assert params["sha256sum"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert set(params.get_list("output_formats")) == {"markdown", "zip"}
    assert markdown == "正文"
    assert meta["engine"] == "mineru"
    assert meta["tier"] == "standard"


async def test_202_then_poll_returns_zip(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"markdown.md": "轮询成功"})
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "task_id": "task-123",
                    "status": "running",
                    "result_url": "/v1/tasks/task-123/result",
                    "status_url": "/v1/tasks/task-123",
                },
                request=request,
            )
        return httpx.Response(200, content=payload, request=request)

    markdown, meta = await _ingest(handler).ingest(pdf, task_id=_task_id("poll"))

    assert markdown == "轮询成功"
    assert meta["mineru_task_id"] == "task-123"
    assert [path for _, path, _ in calls] == [
        "/v1/file_parse",
        "/v1/tasks/task-123/result",
    ]
    assert calls[1][2]["response_format"] == "zip"


async def test_202_without_task_identity_raises_request_error(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"status": "running"}, request=request)

    with pytest.raises(MinerURequestError, match="task_id/result_url"):
        await _ingest(handler).ingest(pdf, task_id=_task_id("noid"))


async def test_auth_401_is_explicit_and_leaks_no_key(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"type": "authentication_error", "code": "invalid_api_key"}},
            request=request,
        )

    with pytest.raises(MinerUAuthError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("auth"))

    message = str(excinfo.value)
    assert "MINERU_API_KEY" in message and "401" in message
    assert "SUPERSECRETKEY" not in message
    assert excinfo.value.fallback_ok is False


async def test_403_is_auth_error(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"type": "auth"}}, request=request)

    with pytest.raises(MinerUAuthError):
        await _ingest(handler).ingest(pdf, task_id=_task_id("forbidden"))


@pytest.mark.parametrize("status", [400, 404, 405, 413, 415, 422])
async def test_request_side_statuses_do_not_fallback(tmp_path, status):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request, status=status) -> httpx.Response:
        return httpx.Response(status, json={"detail": "bad input"}, request=request)

    with pytest.raises(MinerURequestError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id(f"req{status}"))

    assert str(status) in str(excinfo.value)
    assert excinfo.value.fallback_ok is False


async def test_429_is_rate_limited_without_fallback(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "slow down"}, request=request)

    with pytest.raises(MinerUServiceError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("ratelimit"))

    assert "429" in str(excinfo.value)
    assert excinfo.value.fallback_ok is False


async def test_unexpected_status_is_request_error(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, json={"detail": "teapot"}, request=request)

    with pytest.raises(MinerURequestError, match="418") as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("teapot"))

    assert excinfo.value.fallback_ok is False


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_server_errors_fall_back(tmp_path, status):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request, status=status) -> httpx.Response:
        return httpx.Response(status, json={"detail": "boom"}, request=request)

    with pytest.raises(MinerUServiceError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id(f"srv{status}"))

    assert str(status) in str(excinfo.value)
    assert excinfo.value.fallback_ok is True


async def test_connect_error_is_transport_and_fallbackable(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(MinerUTransportError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("connect"))

    assert excinfo.value.fallback_ok is True


async def test_read_timeout_is_timeout_and_fallbackable(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(MinerUTimeoutError) as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("timeout"))

    assert excinfo.value.fallback_ok is True


async def test_polling_exceeds_total_budget_times_out(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={"task_id": "t", "result_url": "/v1/tasks/t/result"},
            request=request,
        )

    ingestor = _ingest(handler, timeout_seconds=1, grace_seconds=0.05, poll_interval=0.01)
    with pytest.raises(MinerUTimeoutError):
        await ingestor.ingest(pdf, task_id=_task_id("poll-timeout"))


async def test_config_missing_url_key_tier(tmp_path):
    pdf = _write_pdf(tmp_path)
    for overrides in ({"base_url": ""}, {"api_key": ""}, {"tier": "turbo"}):
        kwargs = {"base_url": "http://mineru.test:8000", "api_key": "k"}
        kwargs.update(overrides)
        client = MinerUClient(**kwargs)
        with pytest.raises(MinerUConfigError):
            await client.parse_zip(pdf)


async def test_config_error_message_does_not_contain_key(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应发出请求")

    with pytest.raises(MinerUConfigError) as excinfo:
        await _ingest(handler, api_key="").ingest(pdf, task_id=_task_id("nokey"))

    assert "SUPERSECRETKEY" not in str(excinfo.value)
    assert excinfo.value.fallback_ok is False


# --------------------------------------------------------------------------- #
# ZIP 产物处理:校验、安全、媒体落地
# --------------------------------------------------------------------------- #


async def test_non_zip_body_raises_parse_error(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"oops not a zip", request=request)

    with pytest.raises(MinerUParseError, match="魔数") as excinfo:
        await _ingest(handler).ingest(pdf, task_id=_task_id("notzip"))

    assert excinfo.value.fallback_ok is True


async def test_corrupt_zip_raises_parse_error(tmp_path):
    pdf = _write_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04garbage", request=request)

    with pytest.raises(MinerUParseError):
        await _ingest(handler).ingest(pdf, task_id=_task_id("corrupt"))


async def test_zip_slip_is_rejected_and_never_escapes(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"markdown.md": "ok", "../evil.png": _png_bytes()})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    task_id = _task_id("slip")
    with pytest.raises(MinerUParseError, match="安全校验"):
        await _ingest(handler).ingest(pdf, task_id=task_id)

    assert not (settings.UPLOAD_DIR / "evil.png").exists()
    assert not (settings.UPLOAD_DIR / task_id / "evil.png").exists()
    assert not (settings.UPLOAD_DIR / task_id / "mineru").exists()


async def test_too_many_entries_rejected(tmp_path):
    pdf = _write_pdf(tmp_path)
    files = {f"f{i}.txt": b"x" for i in range(2001)}
    files["markdown.md"] = b"ok"
    payload = _zip_bytes(files)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    with pytest.raises(MinerUParseError, match="安全校验"):
        await _ingest(handler).ingest(pdf, task_id=_task_id("many"))


async def test_oversized_member_rejected(tmp_path):
    pdf = _write_pdf(tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("markdown.md", "ok")
        archive.writestr("big.bin", b"\0" * (51 * 1024 * 1024))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=buffer.getvalue(), request=request)

    with pytest.raises(MinerUParseError, match="安全校验"):
        await _ingest(handler).ingest(pdf, task_id=_task_id("big"))


async def test_empty_markdown_raises_parse_error(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"markdown.md": "   \n  "})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    with pytest.raises(MinerUParseError, match="空"):
        await _ingest(handler).ingest(pdf, task_id=_task_id("empty"))


async def test_missing_markdown_member_raises_parse_error(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"images/a.png": _png_bytes()})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    with pytest.raises(MinerUParseError, match="markdown.md"):
        await _ingest(handler).ingest(pdf, task_id=_task_id("nomd"))


async def test_work_dir_removed_on_success_and_on_failure(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes({"markdown.md": "正文"})

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    success_id = _task_id("clean-ok")
    await _ingest(ok_handler).ingest(pdf, task_id=success_id)
    assert not (settings.UPLOAD_DIR / success_id / "mineru").exists()

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"}, request=request)

    fail_id = _task_id("clean-fail")
    with pytest.raises(MinerUServiceError):
        await _ingest(fail_handler).ingest(pdf, task_id=fail_id)
    assert not (settings.UPLOAD_DIR / fail_id / "mineru").exists()


async def test_images_rewritten_maskable_and_richdoc_ready(tmp_path):
    pdf = _write_pdf(tmp_path)
    markdown_src = (
        "【题目】如图,抛物线 $y=ax^2+bx+c$ 与 $x$ 轴交于两点\n"
        "![几何图](images/page_1_image_1.png)\n"
        '<img src="images/page_1_image_2.png" alt="示意" />\n'
        "| 题号 | 答案 |\n| --- | --- |\n| 1 | A |\n"
        "<table><tr><td>2</td><td>B</td></tr></table>"
    )
    payload = _zip_bytes(
        {
            "markdown.md": markdown_src,
            # 两张图故意用不同字节:本用例验证路径重写/遮罩,去重行为由
            # test_mineru_image_anchoring.py 覆盖。
            "images/page_1_image_1.png": _png_bytes() + b"1",
            "images/page_1_image_2.png": _png_bytes() + b"2",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    task_id = _task_id("media")
    markdown, meta = await _ingest(handler).ingest(pdf, task_id=task_id)

    url_1 = f"/static/media/{task_id}/images/page_1_image_1.png"
    url_2 = f"/static/media/{task_id}/images/page_1_image_2.png"
    assert url_1 in markdown and url_2 in markdown
    assert "(images/page_1_image_1.png)" not in markdown
    assert "(images/page_1_image_2.png)" not in markdown
    assert (settings.MEDIA_DIR / task_id / "images" / "page_1_image_1.png").exists()
    assert (settings.MEDIA_DIR / task_id / "images" / "page_1_image_2.png").exists()
    assert meta["images"] == 2
    assert meta["html_tables"] == 1
    assert "normalized_html_image" in meta["warnings"]

    masked, mapping = mask_images(markdown)
    assert len(mapping) == 2
    assert set(mapping.values()) == {f"![几何图]({url_1})", f"![示意]({url_2})"}
    assert "@@IMG0@@" in masked and "@@IMG1@@" in masked

    kinds: set = set()
    _collect_kinds(markdown_to_rich_doc(markdown), kinds)
    assert {"image", "table", "inlineMath"} <= kinds


async def test_media_is_task_scoped(tmp_path):
    pdf = _write_pdf(tmp_path)
    payload = _zip_bytes(
        {"markdown.md": "![x](images/a.png)", "images/a.png": _png_bytes()}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, request=request)

    task_a, task_b = _task_id("scope-a"), _task_id("scope-b")
    await _ingest(handler).ingest(pdf, task_id=task_a)
    await _ingest(handler).ingest(pdf, task_id=task_b)

    assert (settings.MEDIA_DIR / task_a / "images" / "a.png").exists()
    assert (settings.MEDIA_DIR / task_b / "images" / "a.png").exists()
    assert not (settings.UPLOAD_DIR / task_a / "mineru").exists()
    assert not (settings.UPLOAD_DIR / task_b / "mineru").exists()


# --------------------------------------------------------------------------- #
# Markdown 归一化:图片 / 表格 / 公式 / 残留 HTML
# --------------------------------------------------------------------------- #


def test_normalize_img_variants():
    src = (
        '图1 <img src="images/a.png" alt="甲" /> '
        "图2 <img src=images/b.png> 图3 <img alt='无src' />"
    )
    out, warnings, _ = normalize_mineru_markdown(src)
    assert "![甲](images/a.png)" in out
    assert "![](images/b.png)" in out
    assert "<img" not in out
    assert "normalized_html_image" in warnings


def test_normalize_simple_html_table_to_gfm():
    src = "<table><tr><th>题号</th><th>答案</th></tr><tr><td>1</td><td>A</td></tr></table>"
    out, warnings, count = normalize_mineru_markdown(src)
    assert count == 1
    assert out.splitlines()[0] == "| 题号 | 答案 |"
    assert "| --- | --- |" in out
    assert "| 1 | A |" in out
    assert "<table" not in out
    assert warnings == []


def test_normalize_rowspan_colspan_keeps_all_text():
    src = (
        '<table><tr><td rowspan="2">答案</td><td>1</td><td>2</td></tr>'
        "<tr><td>A</td><td>B</td></tr></table>"
        '<table><tr><td colspan="2">合</td></tr><tr><td>x</td><td>y</td></tr></table>'
    )
    out, warnings, count = normalize_mineru_markdown(src)
    assert count == 2
    for text in ("答案", "1", "2", "A", "B", "合", "x", "y"):
        assert text in out
    assert "<table" not in out and "<td" not in out
    assert "manual_review:html_table:0" in warnings
    assert "manual_review:html_table:1" in warnings


def test_normalize_nested_and_unclosed_table_keeps_text():
    nested = (
        "<table><tr><td>外<table><tr><td>内1</td><td>内2</td></tr></table></td></tr></table>"
    )
    out, warnings, _ = normalize_mineru_markdown(nested)
    assert "外" in out and "内1" in out and "内2" in out
    assert "<table" not in out
    assert any(w.startswith("manual_review:html_table:0") for w in warnings)

    unclosed = "<table><tr><td>缺闭合文字"
    out2, _, _ = normalize_mineru_markdown(unclosed)
    assert "缺闭合文字" in out2
    assert "<table" not in out2


def test_normalize_formulas_preserved_and_delimiters_converted():
    src = (
        "行内 $x^2$ 行间 $$\\frac{1}{2}$$ "
        "\\(\\sqrt{2}\\) 块级 \\[\\int_0^1 x\\,dx\\]"
    )
    out, _, _ = normalize_mineru_markdown(src)
    assert "$x^2$" in out
    assert "$$\\frac{1}{2}$$" in out
    assert "$\\sqrt{2}$" in out
    assert "$$\\int_0^1 x\\,dx$$" in out
    assert "\\(" not in out and "\\[" not in out


def test_normalize_latex_conversion_skips_code_fence():
    src = "```\n\\(x\\)\n```\n\n正文 \\(y\\)"
    out, _, _ = normalize_mineru_markdown(src)
    assert "\\(x\\)" in out
    assert "$y$" in out


def test_normalize_keeps_inequality_text():
    src = "若 a<b 且 b>c 则 2<3>1"
    out, warnings, _ = normalize_mineru_markdown(src)
    assert out == src
    assert warnings == []


def test_normalize_strips_block_html_but_keeps_text():
    src = '<div style="color:red">整段说明</div><p>下一段</p>'
    out, warnings, _ = normalize_mineru_markdown(src)
    assert "整段说明" in out and "下一段" in out
    assert "<div" not in out and "<p>" not in out
    assert "stripped_residual_html" in warnings
