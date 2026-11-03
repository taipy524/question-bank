"""MinerU PDF 解析摄取:调用自托管 MinerU 4.0 V1 HTTP API,把解析产物 ZIP 归一成
可直接进入现有 markdown 管线的正文与图片。

同步 ``/upload/pdf`` 与异步 worker 由 ``PdfProcessor`` 单点接入本模块;抽取(Prompt/
AI/结构化)、审核与入库全部复用现有流程,这里只负责"PDF → Markdown + 媒体落盘"。

接口依据(取自在线 ``GET /openapi.json`` 与实测,非假设):
- ``POST {base}/v1/file_parse``,``Authorization: Bearer <key>``;请求体用原始字节
  ``application/octet-stream``(带 Content-Length)。**实测**:``filename``/``sha256sum``
  仅对 raw 上传有效,放进 multipart 会被服务端 400 ``invalid_request`` 拒绝。
- query ``response_format=zip``、``wait_timeout(1..3600)``、``tier``、``ocr_mode``、
  ``output_formats``、``filename``、``sha256sum``。
- ``200`` 直接返回 ZIP 字节;``202`` 返回 ``TaskStatusResponse``(含 ``task_id`` /
  ``result_url``),后续 ``GET {result_url}?response_format=zip`` 取 200 ZIP 或 202(仍处理中)。
- ``401/403`` 认证失败;``4xx`` 请求/输入问题;``5xx`` 服务端错误。

错误分级(决定是否允许回退旧 PDF 流程,见 ``MinerUError.fallback_ok``):
- 明确报错、**不回退**:`MinerUConfigError`(配置缺失)、`MinerUAuthError`(401/403)、
  `MinerURequestError`(400/404/405/413/415/422 等接口参数或文件问题)。
- 可按 ``MINERU_FALLBACK`` 回退:`MinerUTransportError`(连接失败)、
  `MinerUTimeoutError`(超时)、`MinerUServiceError`(5xx/429/任务丢失)、
  `MinerUParseError`(无效 ZIP、空 Markdown、任务 failed)。

安全:任务目录隔离在 ``UPLOAD_DIR/<task_id>/mineru``,复用 ``ingest.py`` 的
zip-slip 与压缩炸弹上限;临时目录无论成败都会删除;API Key 只从环境读取,
不进源码、不进日志、不出现在异常文本里。
"""
from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
import logging
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Iterator, Optional

import httpx
from lxml import html as lxml_html
from pydantic import SecretStr

from app.core.config import settings
from app.services.importing.ingest import _rewrite_markdown_images, _safe_extract_zip

logger = logging.getLogger(__name__)

MINERU_WORK_SUBDIR = "mineru"
_MARKDOWN_NAME = "markdown.md"
_ZIP_MAGIC = b"PK"
_TIERS = frozenset({"flash", "basic", "standard", "advanced"})
_DEFAULT_POLL_INTERVAL = 1.0
_DEFAULT_GRACE_SECONDS = 15.0


class MinerUError(ValueError):
    """MinerU 调用失败基类。``fallback_ok`` 决定 ``PdfProcessor`` 是否允许回退旧流程。"""

    code = "mineru_error"
    fallback_ok = False

    def __init__(self, message: str, *, fallback_ok: Optional[bool] = None) -> None:
        super().__init__(message)
        if fallback_ok is not None:
            self.fallback_ok = fallback_ok


class MinerUConfigError(MinerUError):
    """配置缺失或取值非法(MINERU_API_URL / MINERU_API_KEY / MINERU_TIER)。"""

    code = "config"


class MinerUAuthError(MinerUError):
    """服务端拒绝认证(401/403)。"""

    code = "auth"


class MinerURequestError(MinerUError):
    """请求或输入被服务端拒绝(400/404/405/413/415/422/未预期状态)。"""

    code = "request"


class MinerUTransportError(MinerUError):
    """网络连接失败。"""

    code = "transport"
    fallback_ok = True


class MinerUTimeoutError(MinerUError):
    """请求或轮询超过总时限。"""

    code = "timeout"
    fallback_ok = True


class MinerUServiceError(MinerUError):
    """服务端错误(5xx/429/任务结果丢失)。"""

    code = "server"
    fallback_ok = True


class MinerUParseError(MinerUError):
    """产物不可用:无效 ZIP、缺 markdown.md、空 Markdown、任务 failed。"""

    code = "parse"
    fallback_ok = True


class MinerUClient:
    """MinerU V1 HTTP 客户端:单次提交 + 有界轮询,不重复提交。"""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tier: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        grace_seconds: float = _DEFAULT_GRACE_SECONDS,
    ) -> None:
        if base_url is None:
            base_url = settings.MINERU_API_URL
        if api_key is None:
            api_key = settings.MINERU_API_KEY
        if timeout_seconds is None:
            timeout_seconds = settings.MINERU_TIMEOUT_SECONDS
        if tier is None:
            tier = settings.MINERU_TIER

        if isinstance(api_key, SecretStr):
            api_key = api_key.get_secret_value()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds or 600))
        self.tier = (tier or "").strip()
        self._transport = transport
        self.poll_interval = max(0.01, float(poll_interval))
        self.grace_seconds = max(0.0, float(grace_seconds))

    def __repr__(self) -> str:
        return f"MinerUClient(base_url={self.base_url!r}, tier={self.tier!r})"

    def _require_config(self) -> None:
        if not self.base_url:
            raise MinerUConfigError("未配置 MINERU_API_URL,无法调用 MinerU 解析服务")
        if not self.api_key:
            raise MinerUConfigError(
                "未配置 MINERU_API_KEY(MinerU 服务要求 Bearer 认证,请在部署环境变量中提供)"
            )
        if self.tier not in _TIERS:
            raise MinerUConfigError(
                f"MINERU_TIER 取值无效:{self.tier!r},可选值为 {sorted(_TIERS)}"
            )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def parse_zip(self, file_path: Path) -> tuple[bytes, str]:
        """提交 PDF 并取回解析产物 ZIP。返回 ``(zip_bytes, mineru_task_id)``。"""
        self._require_config()

        data = await asyncio.to_thread(file_path.read_bytes)
        digest = hashlib.sha256(data).hexdigest()
        params = [
            ("response_format", "zip"),
            ("wait_timeout", str(min(self.timeout_seconds, 3600))),
            ("tier", self.tier),
            ("ocr_mode", "auto"),
            ("output_formats", "markdown"),
            ("output_formats", "zip"),
            ("filename", file_path.name),
            ("sha256sum", digest),
        ]
        request_timeout = httpx.Timeout(self.timeout_seconds + 30.0, connect=10.0)
        budget = max(0.1, self.timeout_seconds + self.grace_seconds)

        try:
            async with asyncio.timeout(budget):
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=request_timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        "/v1/file_parse",
                        params=params,
                        headers={
                            **self._headers(),
                            "Content-Type": "application/octet-stream",
                        },
                        content=data,
                    )
                    if response.status_code == 200:
                        return _zip_body(response), ""
                    if response.status_code == 202:
                        payload = _json_payload(response, "提交")
                        task_id = str(payload.get("task_id") or "")
                        result_url = str(
                            payload.get("result_url")
                            or (f"/v1/tasks/{task_id}/result" if task_id else "")
                        )
                        if not result_url:
                            raise MinerURequestError(
                                "MinerU 202 响应缺少 task_id/result_url,无法查询任务结果"
                            )
                        logger.info("MinerU 任务已提交,轮询等待解析完成: task_id=%s", task_id)
                        return await _poll_result(client, result_url, self), task_id
                    _raise_for_status(response, "file_parse")
        except MinerUError:
            raise
        except TimeoutError as exc:
            raise MinerUTimeoutError(
                f"MinerU 解析超时(总时限 {self.timeout_seconds}s)"
            ) from exc
        except httpx.TimeoutException as exc:
            raise MinerUTimeoutError(
                f"MinerU 请求超时({type(exc).__name__})"
            ) from exc
        except httpx.TransportError as exc:
            raise MinerUTransportError(
                f"无法连接 MinerU 服务 {self.base_url}({type(exc).__name__})"
            ) from exc

        raise MinerURequestError("MinerU 未返回可用结果")


async def _poll_result(
    client: httpx.AsyncClient, result_url: str, config: MinerUClient
) -> bytes:
    """轮询任务结果,直到 200 ZIP / 202 继续等待 / 超总时限 / 其它状态。"""
    while True:
        response = await client.get(
            result_url,
            params={"response_format": "zip"},
            headers=config._headers(),
        )
        if response.status_code == 200:
            return _zip_body(response)
        if response.status_code == 202:
            await asyncio.sleep(config.poll_interval)
            continue
        if response.status_code in (404, 410):
            raise MinerUServiceError(
                f"MinerU 任务结果已不可用(HTTP {response.status_code}),"
                "任务索引随服务重启丢失,请重新上传",
                fallback_ok=True,
            )
        _raise_for_status(response, "task result")


def _raise_for_status(response: httpx.Response, where: str) -> None:
    """按状态码逐项分类;请求/输入问题不回退,服务端问题可回退。"""
    status = response.status_code
    snippet = _body_snippet(response)
    if status in (401, 403):
        raise MinerUAuthError(
            f"MinerU 认证失败(HTTP {status},{where}),"
            "请检查 MINERU_API_KEY 是否与服务端一致。" + snippet
        )
    if status in (400, 404, 405, 406, 413, 415, 422):
        raise MinerURequestError(
            f"MinerU 拒绝请求(HTTP {status},{where}),"
            "请检查接口地址、参数或上传文件本身是否符合要求。" + snippet
        )
    if status == 429:
        raise MinerUServiceError(
            f"MinerU 服务限流(HTTP 429,{where}),请稍后重试。" + snippet,
            fallback_ok=False,
        )
    if 500 <= status <= 599:
        raise MinerUServiceError(
            f"MinerU 服务端错误(HTTP {status},{where})。" + snippet
        )
    raise MinerURequestError(
        f"MinerU 返回未预期状态(HTTP {status},{where})。" + snippet
    )


def _body_snippet(response: httpx.Response, limit: int = 300) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    text = " ".join(text.split())
    return f"响应:{text[:limit]}" if text else ""


def _json_payload(response: httpx.Response, where: str) -> dict:
    try:
        payload = response.json()
    except Exception as exc:
        raise MinerURequestError(
            f"MinerU {where}响应不是合法 JSON(HTTP {response.status_code})"
        ) from exc
    if not isinstance(payload, dict):
        raise MinerURequestError(
            f"MinerU {where}响应结构异常(HTTP {response.status_code})"
        )
    return payload


def _zip_body(response: httpx.Response) -> bytes:
    body = response.content
    if not body.startswith(_ZIP_MAGIC):
        raise MinerUParseError("MinerU 返回内容不是 ZIP 产物(缺少 ZIP 魔数)")
    return body


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def _locate_markdown(root: Path) -> Optional[Path]:
    direct = root / _MARKDOWN_NAME
    if direct.is_file():
        return direct
    candidates = sorted(p for p in root.rglob("*.md") if p.is_file())
    if len(candidates) == 1:
        return candidates[0]
    named = [p for p in candidates if p.name == _MARKDOWN_NAME]
    if len(named) == 1:
        return named[0]
    return None


class MinerUIngestor:
    """把 MinerU 解析产物落地成"可进现有 markdown 管线"的正文。"""
    def __init__(self, *, client: Optional[MinerUClient] = None) -> None:
        self._client = client

    async def ingest(self, file_path: Path, *, task_id: str) -> tuple[str, dict]:
        """解析 ``file_path``,返回 ``(markdown, parse_meta)``。

        媒体落在 ``MEDIA_DIR/<task_id>/``;中间产物落在
        ``UPLOAD_DIR/<task_id>/mineru/`` 并在 ``finally`` 中删除。
        """
        client = self._client or MinerUClient()
        started = time.monotonic()
        work_dir = settings.UPLOAD_DIR / task_id / MINERU_WORK_SUBDIR
        out_dir = work_dir / "out"
        await asyncio.to_thread(_reset_dir, work_dir)

        try:
            zip_bytes, mineru_task_id = await client.parse_zip(file_path)
            zip_path = work_dir / "result.zip"
            await asyncio.to_thread(zip_path.write_bytes, zip_bytes)
            await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)

            try:
                await asyncio.to_thread(_safe_extract_zip, zip_path, out_dir)
            except zipfile.BadZipFile as exc:
                raise MinerUParseError("MinerU 返回的 ZIP 无法解压(文件损坏)") from exc
            except ValueError as exc:
                raise MinerUParseError(f"MinerU ZIP 未通过安全校验:{exc}") from exc
            except OSError as exc:
                raise MinerUParseError(f"解压 MinerU ZIP 失败:{exc}") from exc

            markdown_path = await asyncio.to_thread(_locate_markdown, out_dir)
            if markdown_path is None:
                raise MinerUParseError("MinerU ZIP 中没有 markdown.md")

            raw_markdown = await asyncio.to_thread(
                markdown_path.read_text, encoding="utf-8", errors="replace"
            )
            markdown, warnings, html_table_count = normalize_mineru_markdown(raw_markdown)
            markdown = await asyncio.to_thread(
                _rewrite_markdown_images,
                markdown,
                md_dir=markdown_path.parent,
                extract_root=out_dir,
                media_dir=settings.MEDIA_DIR / task_id,
                media_id=task_id,
            )
            # AI 调用前做确定性图片锚定:答案区/无图题/歧义位置的图片不进入 AI 输入。
            markdown, anchoring = await asyncio.to_thread(
                anchor_mineru_images,
                markdown,
                media_dir=settings.MEDIA_DIR / task_id,
                media_id=task_id,
            )
            warnings.extend(anchoring_warnings(anchoring))
            if not markdown.strip():
                raise MinerUParseError("MinerU 返回的 Markdown 为空")

            image_count = len(
                re.findall(
                    rf"!\[[^\]]*\]\(/static/media/{re.escape(task_id)}/", markdown
                )
            )
            meta = {
                "engine": "mineru",
                "tier": client.tier,
                "mineru_task_id": mineru_task_id or None,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "images": image_count,
                "html_tables": html_table_count,
                "warnings": warnings,
                "image_anchoring": anchoring,
            }
            logger.info(
                "MinerU 解析完成: task_id=%s tier=%s images=%s html_tables=%s "
                "anchored=%s unresolved=%s warnings=%s elapsed_ms=%s",
                task_id,
                meta["tier"],
                image_count,
                html_table_count,
                len(anchoring["anchored"]),
                [f"{item['reason']}:{item['image']}" for item in anchoring["unresolved"]],
                warnings,
                meta["elapsed_ms"],
            )
            return markdown, meta
        finally:
            await asyncio.to_thread(shutil.rmtree, work_dir, ignore_errors=True)


def normalize_mineru_markdown(markdown: str) -> tuple[str, list[str], int]:
    """把 MinerU Markdown 归一成现有导入流程可无损消费的形态。

    返回 ``(归一化正文, 需人工复核的 warning 列表, HTML 表格数量)``。

    - ``<img src>`` → Markdown 图片(后续统一重写 ``/static/media/...``)。
    - HTML 表格 → GFM 管道表;rowspan/colspan/嵌套尽量网格展开,不能无损时
      保留全部单元格文本并记 ``manual_review`` warning,绝不静默丢内容。
    - 其余白名单 HTML 标签剥掉保文字,避免原始标签文本污染题干。
    - ``\\(..\\)`` / ``\\[..\\]`` → ``$..$`` / ``$$..$$``;``$..$`` 原样保留。
    """
    warnings: list[str] = []
    text = _img_tags_to_markdown(markdown, warnings)
    text, table_count = _html_tables_to_gfm(text, warnings)
    text = _strip_residual_html(text, warnings)
    text = _normalize_latex_delimiters(text)
    return text, warnings, table_count


_IMG_TAG_RE = re.compile(r"<img\b(?P<attrs>[^>]*?)\s*/?>", re.IGNORECASE)
_IMG_SRC_RE = re.compile(
    r"""\bsrc\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s>]+))""",
    re.IGNORECASE,
)
_IMG_ALT_RE = re.compile(
    r"""\balt\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')""", re.IGNORECASE
)


def _img_tags_to_markdown(markdown: str, warnings: list[str]) -> str:
    changed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed
        attrs = match.group("attrs")
        src_match = _IMG_SRC_RE.search(attrs)
        if not src_match:
            return ""
        src = (src_match.group("dq") or src_match.group("sq") or src_match.group("bare") or "").strip()
        if not src:
            return ""
        alt_match = _IMG_ALT_RE.search(attrs)
        alt = (
            (alt_match.group("dq") or alt_match.group("sq") or "").strip()
            if alt_match
            else ""
        )
        alt = alt.replace("[", "\\[").replace("]", "\\]")
        changed = True
        return f"![{alt}]({src})"

    result = _IMG_TAG_RE.sub(_replace, markdown)
    if changed:
        warnings.append("normalized_html_image")
    return result


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
_TABLE_TOKEN_RE = re.compile(r"<table\b|</table\s*>", re.IGNORECASE)
_GFM_CELL_SEP = " | "


def _iter_html_table_blocks(markdown: str) -> Iterator[tuple[int, int, str]]:
    """按标签配对切出(起, 止, 原文),支持嵌套表与未闭合表(截到文末)。"""
    position = 0
    while True:
        start_match = _TABLE_OPEN_RE.search(markdown, position)
        if start_match is None:
            return
        start = start_match.start()
        depth = 0
        end = None
        for token in _TABLE_TOKEN_RE.finditer(markdown, start):
            if token.group(0).lower().startswith("</"):
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
            else:
                depth += 1
        if end is None:
            end = len(markdown)
        yield start, end, markdown[start:end]
        position = max(end, start + 1)


def _html_tables_to_gfm(markdown: str, warnings: list[str]) -> tuple[str, int]:
    pieces: list[str] = []
    last = 0
    count = 0
    for index, (start, end, block) in enumerate(_iter_html_table_blocks(markdown)):
        pieces.append(markdown[last:start])
        pieces.append(_convert_table_block(block, index=index, warnings=warnings))
        count += 1
        last = end
    pieces.append(markdown[last:])
    return "".join(pieces), count


def _convert_table_block(block: str, *, index: int, warnings: list[str]) -> str:
    table_el = _parse_table(block)
    if table_el is None:
        warnings.append(f"manual_review:html_table:{index}:unparsed")
        return _collapse_html_to_text(block)
    rows, complex_table = _table_to_grid(table_el)
    if not rows:
        warnings.append(f"manual_review:html_table:{index}:unparsed")
        return _collapse_html_to_text(block)
    if complex_table:
        warnings.append(f"manual_review:html_table:{index}")
    return _render_gfm(rows)


def _parse_table(block: str):
    try:
        fragments = lxml_html.fragments_fromstring(block)
    except Exception:
        return None
    for node in fragments:
        if getattr(node, "tag", None) == "table":
            return node
        if hasattr(node, "iter"):
            found = None
            for descendant in node.iter():
                if getattr(descendant, "tag", None) == "table":
                    found = descendant
                    break
            if found is not None:
                return found
    return None


def _span_value(cell, name: str) -> int:
    raw = (cell.get(name) or "").strip()
    if not raw:
        return 1
    try:
        value = int(raw)
    except ValueError:
        return 1
    return max(1, min(value, 100))


def _cell_text(cell) -> str:
    text = cell.text_content().replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("|", r"\|")


def _table_to_grid(table_el) -> tuple[list[list[str]], bool]:
    """把 HTML 表展开成二维文本网格。返回 ``(grid, 是否含无损限制)``。

    合并单元格:首格放文本,被合并的格留空(不重复文本也不丢文本)。
    嵌套表的文本并入所在单元格,并跳过嵌套表自身的行,避免重复。
    """
    complex_table = bool(table_el.xpath(".//table")) or bool(
        table_el.xpath(".//*[@rowspan or @colspan]")
    )
    occupied: dict[tuple[int, int], str] = {}
    row_index = 0
    for tr in table_el.iter("tr"):
        nested = [
            anc
            for anc in tr.iterancestors()
            if anc.tag == "table" and anc is not table_el
        ]
        if nested:
            continue
        cells = [child for child in tr if child.tag in ("td", "th")]
        col_index = 0
        for cell in cells:
            while (row_index, col_index) in occupied:
                col_index += 1
            text = _cell_text(cell)
            rowspan = _span_value(cell, "rowspan")
            colspan = _span_value(cell, "colspan")
            if rowspan > 1 or colspan > 1:
                complex_table = True
            for row_offset in range(rowspan):
                for col_offset in range(colspan):
                    key = (row_index + row_offset, col_index + col_offset)
                    occupied[key] = text if row_offset == 0 and col_offset == 0 else ""
            col_index += colspan
        row_index += 1

    if not occupied:
        return [], complex_table
    max_row = max(key[0] for key in occupied)
    max_col = max(key[1] for key in occupied)
    grid = [
        [occupied.get((row, col), "") for col in range(max_col + 1)]
        for row in range(max_row + 1)
    ]
    return [row for row in grid if any(cell.strip() for cell in row)], complex_table


def _render_gfm(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    if width == 0:
        return ""
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + _GFM_CELL_SEP.join(padded[0]) + " |"]
    lines.append("| " + _GFM_CELL_SEP.join(["---"] * width) + " |")
    lines.extend("| " + _GFM_CELL_SEP.join(row) + " |" for row in padded[1:])
    return "\n".join(lines)


def _collapse_html_to_text(block: str) -> str:
    """HTML 表无法解析时的兜底:剥标签保留全部文字,绝不静默丢内容。"""
    text = _HTML_COMMENT_RE.sub(" ", block)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


_RESIDUAL_TAGS = (
    "br", "hr", "div", "p", "span", "section", "article", "figure", "figcaption",
    "font", "center", "thead", "tbody", "tfoot", "tr", "td", "th", "table",
    "strong", "em", "b", "i", "u", "s", "sup", "sub", "a", "ol", "ul", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "small",
    "label",
)
_RESIDUAL_TAG_RE = re.compile(
    r"<(?P<close>/?)(?P<name>"
    + "|".join(_RESIDUAL_TAGS)
    + r")(?P<attrs>(?:\s+[A-Za-z][A-Za-z0-9_-]*(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*)\s*(?P<self>/?)>",
    re.IGNORECASE,
)
_NEWLINE_TAGS = frozenset(
    {"br", "hr", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"}
)
_AMBIGUOUS_OPEN_TAGS = frozenset({"b", "i", "u", "s"})


def _strip_residual_html(markdown: str, warnings: list[str]) -> str:
    """剥掉剩余白名单 HTML 标签(块级标签保留换行分隔),避免原始标签进题干。

    单字母开标签(如 ``<b>``)在无属性时可能是正文里的比较符号,保留原样交由
    既有转换器标记 needs_review,不做有损猜测。
    """
    original = _HTML_COMMENT_RE.sub("", markdown)

    def _replace(match: re.Match[str]) -> str:
        is_open = not match.group("close") and not match.group("self")
        if is_open and match.group("name").lower() in _AMBIGUOUS_OPEN_TAGS and not match.group("attrs").strip():
            return match.group(0)
        return "\n" if match.group("name").lower() in _NEWLINE_TAGS else ""

    result = _RESIDUAL_TAG_RE.sub(_replace, original)
    result = re.sub(r"\n{3,}", "\n\n", result)
    if result != markdown:
        warnings.append("stripped_residual_html")
    return result


_LATEX_BLOCK_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_LATEX_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_FENCE_RE = re.compile(r"(```.*?```)", re.DOTALL)


def _normalize_latex_delimiters(markdown: str) -> str:
    r"""``\(..\)`` → ``$..$``、``\[..\]`` → ``$$..$$``;跳过代码围栏,不动 ``$..$``。"""
    parts = _FENCE_RE.split(markdown)
    for index in range(0, len(parts), 2):
        segment = parts[index]
        segment = _LATEX_BLOCK_RE.sub(
            lambda match: "$$" + match.group(1).strip() + "$$", segment
        )
        segment = _LATEX_INLINE_RE.sub(
            lambda match: "$" + match.group(1).strip() + "$", segment
        )
        parts[index] = segment
    return "".join(parts)


# --------------------------------------------------------------------------- #
# P2: AI 调用前的图片锚定(确定性规则,不做"最近题目"猜测)
#
# 规则:
# 1. 只在"试卷区"(答案区标题之前)锚定;答案区图片一律不进入 AI 输入。
# 2. 图片必须落在某个题号区段内,且该区段在图片之前出现"如图/图N/下图…"等引用线索;
#    否则视为无法确认归属(no_figure_reference / outside_question)。
# 3. 题号必须严格递增(允许跳 1 个),避免把行首小数/公式误判为题号。
# 4. 图片出现在本题的【答案】/【解析】标记之后 → 无法区分题干图与解析图,按
#    after_answer_marker 保留未解决,不错挂。
# 5. 字节相同的图片复用同一媒体文件,但每个引用及其归属都保留。
# --------------------------------------------------------------------------- #

_QUESTION_START_RE = re.compile(r"(?m)^[ \t]{0,3}(\d{1,2})[ \t]*[.．、](?!\d)[ \t]*(?=\S)")
_TAG_QUESTION_RE = re.compile(r"(?m)^[ \t]*【题目】")
_ANSWER_REGION_RE = re.compile(
    r"(?m)^#{1,6}[ \t]*[^\n]*(?:参考答案|答案与解析|试题解析|答案详解|答案与评分)"
)
_TAG_ANSWER_REGION_RE = re.compile(r"(?m)^[ \t]*【(?:答案区|答案表|统一答案|答案速查)】")
# 图示引用:覆盖「如图」「如题4图」「如题 4 图」「题4图」「第4题图」「图4」「附图」「下图」等写法。
# 分组名用于在 parse_meta 里统计引用类型,并区分"图号"与"题号"。
_FIGURE_CUE_RE = re.compile(
    r"(?P<ru_ti>如题\s*[0-9０-９]+(?:\s*[-－—]\s*[0-9０-９]+)?\s*图)"
    r"|(?P<di_ti>第\s*[0-9０-９]+(?:\s*[-－—]\s*[0-9０-９]+)?\s*题\s*图)"
    r"|(?P<ti_tu>题\s*[0-9０-９]+(?:\s*[-－—]\s*[0-9０-９]+)?\s*图)"
    r"|(?P<ru_tu>如图)"
    r"|(?P<fu_tu>附图)"
    r"|(?P<xia_tu>下图)"
    r"|(?P<shang_tu>上图)"
    r"|(?P<jian_tu>见图)"
    # 「图中」也是常见图形引用(图中阴影/图中点A…);用负向后视排除「地图中/版图中」等普通词。
    r"|(?P<tu_zhong>(?<![地版蓝宏意])图中)"
    r"|(?P<tu_shi>图示)"
    r"|(?P<tu_n>图\s*[0-9０-９]+(?:\s*[-－—]\s*[0-9０-９]+)?)"
)
_CUE_GROUPS = ("ru_ti", "di_ti", "ti_tu", "ru_tu", "fu_tu", "xia_tu", "shang_tu", "jian_tu", "tu_zhong", "tu_shi", "tu_n")
_CUE_QUESTION_GROUPS = ("ru_ti", "di_ti", "ti_tu")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_IMAGE_TOKEN_FULL_RE = re.compile(r"!\[[^\]]*\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
# 选择题选项行首(A. / A．/ A、/ A)):用于把"选项图"挂回对应选项。
_OPTION_LABEL_LINE_RE = re.compile(r"(?m)^[ \t]*(?P<label>[A-D])[ \t]*[.．、)][ \t]*")
_OPTION_LABEL_PREFIX_RE = re.compile(r"^[ \t]*(?P<label>[A-D])[ \t]*[.．、)][ \t]*$")
_ANSWER_MARKER_RE = re.compile(r"(?m)^[ \t]*(?:【答案】|【解析】|【分析】|答案[:：]|解析[:：])")

# 质量门:只排除"无法解码"与"明显过小"的素材。
# 不再依据颜色深浅/填充面积判断(深色几何图、带底纹的截图都是正常插图)。
# 100x144、138x141 这类真实小图会保留;77x43 这类页眉小图标仍会被排除(保留为未解决候选)。
_MIN_IMAGE_MAX_SIDE_PX = 80
_MIN_IMAGE_MIN_SIDE_PX = 48


def _segments_from_starts(
    starts: list[tuple[int, int]], limit: int
) -> list[tuple[int, int, int]]:
    segments: list[tuple[int, int, int]] = []
    for index, (number, position) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else limit
        segments.append((number, position, end))
    return segments


def _numeric_segments_between(
    markdown: str, start: int, end: int
) -> list[tuple[int, int, int]]:
    """在 ``[start, end)`` 内按数字题号分段(编号各自从 1 起,允许跳 1)。"""
    starts: list[tuple[int, int]] = []
    last_number = 0
    for match in _QUESTION_START_RE.finditer(markdown, start, end):
        number = int(match.group(1))
        if number <= last_number or number > last_number + 2:
            continue
        starts.append((number, match.start()))
        last_number = number
    if len(starts) < 2:
        return []
    return _segments_from_starts(starts, end)


def _detect_question_segments(
    markdown: str,
) -> tuple[list[tuple[int, int, int]], Optional[int]]:
    """返回 ``([(题号, 起点, 终点)], 答案区起点)``。

    优先用数字题号(严格递增、允许跳 1,过滤行首小数/公式);数字题号不足 2 个时
    退回 ``【题目】`` 标签分段(标签精准解析格式)。两种结构都不可用时返回空区段。
    """
    numeric_answer = _ANSWER_REGION_RE.search(markdown)
    tag_answer = _TAG_ANSWER_REGION_RE.search(markdown)
    answer_candidates = [m.start() for m in (numeric_answer, tag_answer) if m]
    answer_start = min(answer_candidates) if answer_candidates else None
    limit = answer_start if answer_start is not None else len(markdown)

    numeric_segments = _numeric_segments_between(markdown, 0, limit)
    if len(numeric_segments) >= 2:
        return numeric_segments, answer_start

    tag_starts = [
        (index + 1, match.start())
        for index, match in enumerate(_TAG_QUESTION_RE.finditer(markdown, 0, limit))
    ]
    if len(tag_starts) >= 2:
        return _segments_from_starts(tag_starts, limit), answer_start
    return [], answer_start


def anchor_mineru_images(
    markdown: str, *, media_dir: Path, media_id: str
) -> tuple[str, dict]:
    """按确定性规则把图片锚定到题目,并返回诊断报告。

    未能在唯一题号区段内确认归属的图片会被移出 Markdown(AI 看不到),但记录到
    报告的 ``unresolved`` 里,由调用方写入 ``parse_meta.warnings``。
    """
    segments, answer_start = _detect_question_segments(markdown)
    report: dict = {
        "detected_questions": len(segments),
        "answer_region_start": answer_start,
        "anchored": [],
        "unresolved": [],
        "deduped": [],
        "missing_media": [],
        "missing_figure_questions": [],
        "answer_candidates": [],
        "cue_types": {},
        "cue_strength": {},
        "option_images": [],
        "stats": {},
    }
    tokens = list(_IMAGE_TOKEN_FULL_RE.finditer(markdown))
    if not tokens:
        report["stats"] = _anchoring_stats(report, 0)
        if len(segments) >= 2:
            _report_missing_figure_questions(
                markdown,
                segments=segments,
                answer_start=answer_start,
                tokens=[],
                anchored=[],
                after_marker_candidates={},
                report=report,
                media_id=media_id,
                option_questions=set(),
            )
        return markdown, report
    if len(segments) < 2:
        # 结构不可用:不清空图片,交给现有结构化/AI 流程,并留下可见诊断。
        report["skipped_reason"] = "no_question_structure"
        report["images_kept"] = len(tokens)
        markdown = _dedupe_media_files(
            markdown, media_dir=media_dir, media_id=media_id, report=report
        )
        report["stats"] = _anchoring_stats(report, len(tokens))
        return markdown, report

    # 纯图片选项:把图片按原顺序移到 A/B/C/D 标签之后,交给 AI 归入对应选项。
    markdown = _attach_option_images(markdown, segments=segments, media_id=media_id)
    tokens = list(_IMAGE_TOKEN_FULL_RE.finditer(markdown))

    removals: list[tuple[int, int]] = []
    after_marker_candidates: dict[int, list[str]] = {}
    for token in tokens:
        url = token.group("url")
        image = _image_ref(url, media_id)
        position = token.start()

        if answer_start is not None and position >= answer_start:
            removals.append((position, token.end()))
            report["unresolved"].append({"image": image, "reason": "answer_region"})
            continue

        segment = next(
            (item for item in segments if item[1] <= position < item[2]), None
        )
        if segment is None:
            removals.append((position, token.end()))
            report["unresolved"].append({"image": image, "reason": "outside_question"})
            continue

        number, segment_start, _ = segment
        option_label = _option_label_of_line(markdown, position)
        if option_label is not None:
            # 已位于选项行(移动后或 MinerU 原生如此):归入选项,不再按题干规则处理。
            report["option_images"].append(
                {"question": number, "option": option_label, "image": image}
            )
            continue
        if url.startswith(f"/static/media/{media_id}/"):
            local_path = media_dir / url[len(f"/static/media/{media_id}/"):]
            if not local_path.is_file():
                removals.append((position, token.end()))
                report["unresolved"].append(
                    {"image": image, "reason": "missing_media", "question": number}
                )
                continue
            issue = _image_quality_issue(local_path)
            if issue is not None:
                removals.append((position, token.end()))
                report["unresolved"].append(
                    {"image": image, "reason": issue, "question": number}
                )
                continue

        cue = _FIGURE_CUE_RE.search(markdown, segment_start, position)
        if cue is None:
            removals.append((position, token.end()))
            report["unresolved"].append(
                {"image": image, "reason": "no_figure_reference", "question": number}
            )
            continue

        referenced = _cue_question_number(cue)
        if referenced is not None and referenced != number:
            removals.append((position, token.end()))
            report["unresolved"].append(
                {
                    "image": image,
                    "reason": "cue_question_mismatch",
                    "question": number,
                    "cue_question": referenced,
                }
            )
            continue

        marker = _ANSWER_MARKER_RE.search(markdown, segment_start, position)
        if marker is not None:
            removals.append((position, token.end()))
            report["unresolved"].append(
                {"image": image, "reason": "after_answer_marker", "question": number}
            )
            after_marker_candidates.setdefault(number, []).append(image)
            continue

        report["anchored"].append({"question": number, "image": image})
        category = _cue_category(cue)
        report["cue_types"][category] = report["cue_types"].get(category, 0) + 1
        strength = _cue_strength(category)
        report["cue_strength"][strength] = report["cue_strength"].get(strength, 0) + 1

    option_questions = {item["question"] for item in report["option_images"]}
    _report_missing_figure_questions(
        markdown,
        segments=segments,
        answer_start=answer_start,
        tokens=tokens,
        anchored=report["anchored"],
        after_marker_candidates=after_marker_candidates,
        report=report,
        media_id=media_id,
        option_questions=option_questions,
    )
    markdown = _remove_spans(markdown, removals)
    markdown = _dedupe_media_files(
        markdown, media_dir=media_dir, media_id=media_id, report=report
    )
    report["stats"] = _anchoring_stats(report, len(tokens))
    return markdown, report


def _report_missing_figure_questions(
    markdown: str,
    *,
    segments: list[tuple[int, int, int]],
    answer_start: Optional[int],
    tokens: list[re.Match],
    anchored: list[dict],
    after_marker_candidates: dict[int, list[str]],
    report: dict,
    media_id: str,
    option_questions: Optional[set[int]] = None,
) -> None:
    """题干有"如图"等引用但没有锚定图片时告警;答案区同题号图片仅作候选提示。"""
    anchored_numbers = {item["question"] for item in anchored} | (option_questions or set())
    answer_images: dict[int, list[str]] = {}
    if answer_start is not None:
        for number, seg_start, seg_end in _numeric_segments_between(
            markdown, answer_start, len(markdown)
        ):
            images = [
                _image_ref(token.group("url"), media_id)
                for token in tokens
                if seg_start <= token.start() < seg_end
            ]
            if images:
                answer_images[number] = images

    for number, seg_start, seg_end in segments:
        if number in anchored_numbers:
            continue
        if not _FIGURE_CUE_RE.search(markdown, seg_start, seg_end):
            continue
        report["missing_figure_questions"].append(number)
        candidates = list(
            dict.fromkeys(
                answer_images.get(number, []) + after_marker_candidates.get(number, [])
            )
        )
        if candidates:
            report["answer_candidates"].append(
                {"question": number, "images": candidates}
            )


def _image_quality_issue(path: Path) -> Optional[str]:
    """返回 ``"unreadable_image"`` / ``"degenerate_image"`` / ``None``。

    只做最小必要判定:解码失败 → unreadable_image;明显过小 → degenerate_image。
    颜色深浅与填充面积不作为判定依据。
    """
    try:
        from PIL import Image  # 已有依赖(pillow)
    except Exception:
        return None
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return "unreadable_image"
    if width <= 0 or height <= 0:
        return "unreadable_image"
    if max(width, height) < _MIN_IMAGE_MAX_SIDE_PX or min(width, height) < _MIN_IMAGE_MIN_SIDE_PX:
        return "degenerate_image"
    return None


def _is_degenerate_image(path: Path) -> bool:
    """兼容旧命名:是否存在质量问题时视为退化图。"""
    return _image_quality_issue(path) is not None


def _cue_category(match: "re.Match[str]") -> str:
    for name in _CUE_GROUPS:
        if match.group(name):
            return name
    return "other"


def _cue_strength(category: str) -> str:
    """strong = 带明确题号(如题4图/第4题图/题4图);weak = 仅语义指向图形(如图/图中/下图…)。"""
    return "strong" if category in _CUE_QUESTION_GROUPS else "weak"


def _cue_question_number(match: "re.Match[str]") -> Optional[int]:
    """从「如题4图/第4题图/题4图」中解析题号;「图4」只是图号,不算题号。"""
    for name in _CUE_QUESTION_GROUPS:
        text = match.group(name)
        if not text:
            continue
        digits = re.search(r"[0-9０-９]+", text)
        if digits:
            return int(digits.group(0).translate(_FULLWIDTH_DIGITS))
    return None


def _anchoring_stats(report: dict, seen: int) -> dict:
    reasons: dict[str, int] = {}
    for item in report.get("unresolved") or []:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    return {
        "images_seen": seen,
        "anchored": len(report.get("anchored") or []),
        "unresolved": len(report.get("unresolved") or []),
        "by_reason": reasons,
        "cue_types": dict(report.get("cue_types") or {}),
        "cue_strength": dict(report.get("cue_strength") or {}),
        "option_images": len(report.get("option_images") or []),
        "deduped": len(report.get("deduped") or []),
        "missing_media": len(report.get("missing_media") or []),
    }


_OPTION_SPAN_PUNCT = " \t\r\n.．、（）()，,;；:："


def _option_label_of_line(markdown: str, position: int) -> Optional[str]:
    """若图片位于某选项行首标签之后(如 ``A. ![](...)``),返回该选项标签。"""
    line_start = markdown.rfind("\n", 0, position) + 1
    prefix = markdown[line_start:position]
    match = _OPTION_LABEL_PREFIX_RE.match(prefix)
    return match.group("label") if match else None


def _apply_edits(
    text: str, removals: list[tuple[int, int]], insertions: dict[int, str]
) -> str:
    events: list[tuple[int, int, int, str]] = []
    for start, end in removals:
        events.append((start, 1, end, ""))
    for position, payload in insertions.items():
        events.append((position, 0, position, payload))
    events.sort(key=lambda item: (item[0], item[1]))

    out: list[str] = []
    cursor = 0
    for position, kind, end, payload in events:
        if position < cursor:
            if kind == 0:
                out.append(payload)
            continue
        out.append(text[cursor:position])
        if kind == 0:
            out.append(payload)
            cursor = position
        else:
            cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _attach_option_images(
    markdown: str, *, segments: list[tuple[int, int, int]], media_id: str
) -> str:
    """把"纯图片选项"题目的图片按原始顺序移到 A/B/C/D 标签之后。

    仅在以下条件同时满足时移动(否则保持原样):
    - 题段内至少有 2 个选项标签;
    - 去掉图片 token 后,各选项内容为空(纯图片选项);
    - 图片数 >= 选项数。

    移动只发生在题目内部,不改变文档总长度与分段边界。
    """
    removals: list[tuple[int, int]] = []
    insertions: dict[int, str] = {}

    for _number, segment_start, segment_end in segments:
        segment = markdown[segment_start:segment_end]
        labels = list(_OPTION_LABEL_LINE_RE.finditer(segment))
        if len(labels) < 2:
            continue

        image_tokens = [
            token
            for token in _IMAGE_TOKEN_FULL_RE.finditer(segment)
            if token.start() > labels[0].start()
        ]
        if len(image_tokens) < len(labels):
            continue

        pure_image_options = True
        for index, label in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(segment)
            body = _IMAGE_TOKEN_FULL_RE.sub("", segment[label.end():end])
            if body.strip(_OPTION_SPAN_PUNCT):
                pure_image_options = False
                break
        if not pure_image_options:
            continue

        for index, label in enumerate(labels):
            token = image_tokens[index]
            removals.append(
                (segment_start + token.start(), segment_start + token.end())
            )
            insertions[segment_start + label.end()] = token.group(0)

    if not removals:
        return markdown
    return _apply_edits(markdown, removals, insertions)


def _image_basename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _image_ref(url: str, media_id: str) -> str:
    """报告里统一用相对媒体目录的路径(如 ``images/page_0_image_1.jpg``)。"""
    prefix = f"/static/media/{media_id}/"
    return url[len(prefix):] if url.startswith(prefix) else _image_basename(url)


def _remove_spans(markdown: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return markdown
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        pieces.append(markdown[cursor:start])
        cursor = end
    pieces.append(markdown[cursor:])
    return "".join(pieces)


def _dedupe_media_files(
    markdown: str, *, media_dir: Path, media_id: str, report: dict
) -> str:
    """字节相同的图片复用首个媒体文件;所有引用都保留(重写 URL,不删引用)。"""
    prefix = f"/static/media/{media_id}/"
    canonical_by_digest: dict[str, str] = {}
    replacements: list[tuple[int, int, str]] = []
    duplicate_paths: list[Path] = []

    for token in _IMAGE_TOKEN_FULL_RE.finditer(markdown):
        url = token.group("url")
        if not url.startswith(prefix):
            continue
        relative = url[len(prefix):]
        path = media_dir / relative
        if not path.is_file():
            report["missing_media"].append(relative)
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            report["missing_media"].append(relative)
            continue
        canonical = canonical_by_digest.get(digest)
        if canonical is None:
            canonical_by_digest[digest] = url
        elif canonical != url:
            report["deduped"].append({"image": relative, "canonical": canonical[len(prefix):]})
            replacements.append((token.start("url"), token.end("url"), canonical))
            duplicate_paths.append(path)

    for start, end, new_url in sorted(replacements, reverse=True):
        markdown = markdown[:start] + new_url + markdown[end:]

    for path in duplicate_paths:
        relative = str(path.relative_to(media_dir))
        if f"{prefix}{relative}" not in markdown:
            try:
                path.unlink()
            except OSError:
                pass
    return markdown


def anchoring_warnings(report: dict) -> list[str]:
    """把锚定报告转成 ``parse_meta.warnings`` 里的可读条目。"""
    warnings: list[str] = []
    reasons: dict[str, int] = {}
    for item in report.get("unresolved") or []:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    for reason in sorted(reasons):
        warnings.append(f"image_unresolved:{reason}:{reasons[reason]}")
    if report.get("missing_media"):
        warnings.append(f"image_missing_media:{len(report['missing_media'])}")
    if report.get("deduped"):
        warnings.append(f"image_deduped:{len(report['deduped'])}")
    for number in report.get("missing_figure_questions") or []:
        warnings.append(f"image_missing_for_figure_question:{number}")
    for item in report.get("answer_candidates") or []:
        warnings.append(
            "image_candidate_for_question:%d:%s"
            % (item["question"], ",".join(item["images"]))
        )
    if report.get("skipped_reason") == "no_question_structure":
        warnings.append("image_anchoring_skipped:no_question_structure")
    if reasons or report.get("missing_figure_questions"):
        warnings.append("manual_review:image_anchoring")
    return warnings


mineru_ingestor = MinerUIngestor()