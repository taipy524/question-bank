"""PDF 导入摄取：优先用 MinerU 转 markdown 走文本管线，失败按配置回退到
“有文本层走文本管线、扫描件逐页视觉管线”的原有实现。"""
from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.doc_processor import doc_processor
from app.services.importing.mineru_ingest import MinerUError, mineru_ingestor
from app.services.importing.provider_config import resolve_active_provider

logger = logging.getLogger(__name__)

# 全文有效字符低于该值视为扫描件（无可用文本层）。
_MIN_TEXT_CHARS = 60
# 扫描件渲染 DPI：150 对 A4 约 1240x1754，视觉抽取足够且体积可控。
_RENDER_DPI = 150
# 插图候选过滤：短于此尺寸(pt)的是装饰小图标(题号圆点/考点树节点),不值得入题。
_FIGURE_MIN_PT = 30.0
# 覆盖页面面积比 ≥ 该值的是整页水印/背景图,跳过。
_FIGURE_MAX_PAGE_FRACTION = 0.3
# 插图按 bbox 裁剪页面渲染的 DPI(图形多为小幅坐标图/几何图,200 足够清晰)。
_FIGURE_RENDER_DPI = 200


def _require_fitz():
    try:
        import fitz  # noqa: PLC0415 - pymupdf 是可选的重型依赖,延迟导入
    except ImportError as exc:  # pragma: no cover - 取决于运行环境是否装了依赖
        raise ValueError("服务器未安装 pymupdf,无法解析 PDF") from exc
    return fitz


def extract_pdf_text(path: Path) -> str:
    """按页提取文本层,页间空行分隔。"""
    fitz = _require_fitz()
    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text").strip())
    return "\n\n".join(part for part in parts if part)


def extract_pdf_markdown(path: Path, task_id: str) -> str:
    """文本层 + 内嵌插图 → markdown,插图按内容流顺序注入 `![...](...)`。

    插图按 bbox 裁剪页面渲染成 PNG 落盘到 ``MEDIA_DIR/task_id``,改写成公开 URL,
    交给下游 mask/restore(`@@IMGn@@`)与 markdown→RichDoc 管线还原成 image 节点。
    过滤两类噪声:整页水印/背景(覆盖 ≥30% 页面)与装饰小图标(短边 <30pt)。
    无插图的页面原样走 `get_text("text")`,与旧版逐字节一致。
    """
    fitz = _require_fitz()
    media_dir = settings.MEDIA_DIR / task_id
    parts: list[str] = []
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            page_dict = page.get_text("dict")
            figures: dict[int, str] = {}
            counter = 0
            for block_index, block in enumerate(page_dict["blocks"]):
                if block.get("type") != 1:
                    continue
                bbox = fitz.Rect(block["bbox"])
                visible = bbox & page.rect
                if visible.is_empty:
                    continue
                if visible.get_area() >= page.rect.get_area() * _FIGURE_MAX_PAGE_FRACTION:
                    continue
                if max(bbox.width, bbox.height) < _FIGURE_MIN_PT:
                    continue
                # 按 bbox 裁剪渲染而非取原始图片资源:很多试卷 PDF 的"图形"是整页截图
                # 再经内容流裁剪露出的局部,原始资源会带出整页截图。
                pix = page.get_pixmap(clip=visible, dpi=_FIGURE_RENDER_DPI)
                data = pix.tobytes("png")
                if not data:
                    continue
                counter += 1
                name = f"pdf_p{page_index + 1}_{counter}.png"
                if counter == 1:
                    media_dir.mkdir(parents=True, exist_ok=True)
                (media_dir / name).write_bytes(data)
                figures[block_index] = f"![试卷插图](/static/media/{task_id}/{name})"

            if not figures:
                text = page.get_text("text").strip()
                if text:
                    parts.append(text)
                continue

            # 内容流顺序重建文本,插图块按原位插入(与 get_text("text") 等价,见测试)。
            chunks: list[str] = []
            for block_index, block in enumerate(page_dict["blocks"]):
                if block.get("type") == 0:
                    chunks.append(
                        "\n".join(
                            "".join(span["text"] for span in line["spans"])
                            for line in block["lines"]
                        )
                    )
                elif block_index in figures:
                    chunks.append(figures[block_index])
            part = "\n".join(chunks).strip()
            if part:
                parts.append(part)
    return "\n\n".join(parts)


def render_pdf_pages(path: Path) -> list[bytes]:
    """把每页渲染成 PNG 字节,供视觉抽取使用。"""
    fitz = _require_fitz()
    pages: list[bytes] = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=_RENDER_DPI)
            pages.append(pix.tobytes("png"))
    return pages


class PdfProcessor:
    async def process_pdf(
        self,
        file_path: Path,
        db: AsyncSession,
        filename: Optional[str] = None,
        task_id: Optional[str] = None,
        mode: str = "extract",
        method: str = "ai",
        subject_id: Optional[int] = None,
    ) -> dict:
        """解析 PDF:启用 MinerU 时优先转 markdown,否则走原有的文本/扫描双路径。"""
        media_task_id = task_id or str(uuid.uuid4())
        mineru_failure: list[MinerUError] = []

        # MINERU_ENABLED 默认 False;测试里用 getattr 兜底以兼容仅带 MEDIA_DIR 的桩配置。
        if getattr(settings, "MINERU_ENABLED", False):
            mineru_result = await self._process_with_mineru(
                file_path,
                db,
                filename=filename,
                task_id=media_task_id,
                mode=mode,
                method=method,
                subject_id=subject_id,
                on_fallback=mineru_failure.append,
            )
            if mineru_result is not None:
                return mineru_result
            logger.info("回退到内置 PDF 解析: %s", file_path.name)

        try:
            return await self._process_legacy_pdf(
                file_path,
                db,
                filename=filename,
                task_id=media_task_id,
                mode=mode,
                method=method,
                subject_id=subject_id,
            )
        except ValueError as exc:
            # P4:MinerU 回退后的失败要带上前因,便于用户区分"服务不可用"与"文件/模型问题"。
            if mineru_failure:
                failure = mineru_failure[0]
                raise ValueError(
                    f"MinerU 不可用（{failure.code}），已回退内置 PDF 解析但仍失败：{exc}"
                ) from exc
            raise

    async def _process_legacy_pdf(
        self,
        file_path: Path,
        db: AsyncSession,
        *,
        filename: Optional[str],
        task_id: str,
        mode: str,
        method: str,
        subject_id: Optional[int],
    ) -> dict:
        """原有的内置解析路径(文本层走 markdown,扫描件逐页视觉)。"""
        media_task_id = task_id
        text = await asyncio.to_thread(extract_pdf_text, file_path)
        if len(text) >= _MIN_TEXT_CHARS:
            logger.info("PDF 文本层可用 (%d chars),按文本导入: %s", len(text), file_path.name)
            # 插图与后续 markdown 摄取共用同一 task_id,媒体落在 MEDIA_DIR/task_id 下。
            markdown = await asyncio.to_thread(extract_pdf_markdown, file_path, media_task_id)
            return await doc_processor.process_markdown(
                markdown,
                db,
                filename=filename or file_path.name,
                task_id=media_task_id,
                mode=mode,
                method=method,
                subject_id=subject_id,
            )

        logger.info("PDF 无可用文本层,按扫描件逐页视觉抽取: %s", file_path.name)
        # 扫描件完全依赖视觉模型:先确认已配置,避免逐页“静默 0 题”。
        provider_name, _ = await resolve_active_provider(db, is_vision=True)
        if not provider_name:
            raise ValueError(
                "扫描版 PDF 没有文本层，需要 AI 视觉模型识别。"
                "请先在「系统设置 → AI 配置」配置并激活视觉模型，或改用带文本层的 PDF。"
            )
        pages = await asyncio.to_thread(render_pdf_pages, file_path)
        if not pages:
            raise ValueError("PDF 没有可处理的页面")

        merged: list = []
        first: dict = {}
        for index, png in enumerate(pages):
            try:
                page_result = await doc_processor.process_image(
                    io.BytesIO(png), db, mode=mode, subject_id=subject_id
                )
            except Exception as exc:
                detail = str(exc)
                raise ValueError(
                    f"扫描版 PDF 需要 AI 视觉模型支持（第 {index + 1}/{len(pages)} 页处理失败: {detail}）"
                ) from exc
            if not first:
                first = page_result
            merged.extend(page_result.get("questions") or [])

        return {
            "task_id": first.get("task_id"),
            "image_url": first.get("image_url"),
            "questions": merged,
            "paper": first.get("paper"),
        }

    async def _process_with_mineru(
        self,
        file_path: Path,
        db: AsyncSession,
        *,
        filename: Optional[str],
        task_id: str,
        mode: str,
        method: str,
        subject_id: Optional[int],
        on_fallback: Optional[Any] = None,
    ) -> Optional[dict]:
        """MinerU 解析 → 交给现有 markdown 管线。

        返回 None 表示"允许回退"调用方继续走旧流程;不可回退的错误(配置/认证/
        请求问题,或 MINERU_FALLBACK=false)直接抛出,由调用方映射成 400/任务失败。
        """
        started = time.monotonic()
        try:
            markdown, meta = await mineru_ingestor.ingest(file_path, task_id=task_id)
        except MinerUError as exc:
            allow_fallback = getattr(settings, "MINERU_FALLBACK", True) and exc.fallback_ok
            if allow_fallback:
                logger.warning(
                    "MinerU 解析失败(%s),按配置回退原 PDF 流程: %s", exc.code, exc
                )
                if on_fallback is not None:
                    on_fallback(exc)
                return None
            logger.error("MinerU 解析失败(%s)且不允许回退: %s", exc.code, exc)
            raise

        meta["parse_seconds"] = round(time.monotonic() - started, 3)
        logger.info(
            "MinerU 解析成功: tier=%s images=%s html_tables=%s warnings=%s parse_seconds=%s",
            meta.get("tier"),
            meta.get("images"),
            meta.get("html_tables"),
            meta.get("warnings"),
            meta.get("parse_seconds"),
        )
        result = await doc_processor.process_markdown(
            markdown,
            db,
            filename=filename or file_path.name,
            task_id=task_id,
            mode=mode,
            method=method,
            subject_id=subject_id,
        )
        # P1:AI 抽取阶段丢弃/多写占位符的告警并入 parse_meta,让用户可见。
        ai_warnings = result.pop("warnings", None)
        if ai_warnings:
            meta.setdefault("warnings", []).extend(ai_warnings)
        result["parse_meta"] = meta
        return result


pdf_processor = PdfProcessor()
