import pymupdf
import pytest

from app.services import pdf_processor as pdf_processor_module
from app.services.pdf_processor import (
    extract_pdf_markdown,
    extract_pdf_text,
    pdf_processor,
    render_pdf_pages,
)

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


def _make_text_pdf(path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    # 内置 Helvetica 无法编码中文，必须用 CJK 字体，否则文本层是 .notdef 占位符。
    page.insert_text((72, 72), text, fontsize=11, fontname="china-s")
    doc.save(path)
    doc.close()


def _make_scanned_pdf(path) -> None:
    """无文本层的“扫描件”：页面只有一张图。"""
    seed = pymupdf.open()
    seed_page = seed.new_page()
    seed_page.insert_text((72, 72), "扫描内容", fontsize=11, fontname="china-s")
    pix = seed_page.get_pixmap(dpi=150)
    seed.close()

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()


def _png(width: int, height: int) -> bytes:
    seed = pymupdf.open()
    page = seed.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=(0, 0.5, 1), fill=(0, 0.5, 1))
    pix = page.get_pixmap()
    data = pix.tobytes("png")
    seed.close()
    return data


FIGURE_TEXT = (
    "【题目】如图,一次函数图象经过点 P,请判断 k 的符号\n"
    "【题型】单选\n"
    "【选项】A. k>0  B. k<0\n"
    "【答案】A\n"
    "【解析】本题考查一次函数图象经过象限与系数符号之间的对应关系\n"
)


def _make_text_pdf_with_images(path, text: str) -> None:
    """带文本层的 PDF:题干文本块之间夹一个正常插图,另有整页水印与装饰小图标。"""
    doc = pymupdf.open()
    page = doc.new_page()
    lines = text.split("\n")
    # 题干块 → 插图块 → 其余标签块:插图落在内容流的题目文本内。
    page.insert_text((72, 72), lines[0], fontsize=11, fontname="china-s")
    page.insert_image(pymupdf.Rect(300, 60, 400, 140), stream=_png(200, 160))
    page.insert_text((72, 160), "\n".join(lines[1:]), fontsize=11, fontname="china-s")
    # 整页水印:覆盖面积 ≥30%,应被跳过。
    page.insert_image(page.rect, stream=_png(600, 800))
    # 装饰小图标(20x20pt):短边 <30pt,应被跳过。
    page.insert_image(pymupdf.Rect(72, 200, 92, 220), stream=_png(40, 40))
    doc.save(path)
    doc.close()


def test_extract_pdf_text_keeps_tags(tmp_path):
    pdf = tmp_path / "tags.pdf"
    _make_text_pdf(pdf, TAG_TEXT)

    text = extract_pdf_text(pdf)

    assert "【题目】" in text
    assert "【答案】A" in text


def test_render_pdf_pages_returns_png_for_scanned_pdf(tmp_path):
    pdf = tmp_path / "scanned.pdf"
    _make_scanned_pdf(pdf)

    assert len(extract_pdf_text(pdf).strip()) < 60
    pages = render_pdf_pages(pdf)
    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG")


async def test_process_pdf_text_layer_uses_structured_parser(tmp_path, db_session):
    pdf = tmp_path / "tags.pdf"
    _make_text_pdf(pdf, TAG_TEXT)

    result = await pdf_processor.process_pdf(
        pdf, db_session, filename="tags.pdf", method="structured"
    )

    assert len(result["questions"]) == 2
    assert result["questions"][0]["content"] == "下列关于集合的说法正确的是"


async def test_process_pdf_scanned_without_vision_model_raises(tmp_path, db_session):
    pdf = tmp_path / "scanned.pdf"
    _make_scanned_pdf(pdf)

    with pytest.raises(ValueError, match="视觉模型"):
        await pdf_processor.process_pdf(pdf, db_session, filename="scanned.pdf")


def _patch_media_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pdf_processor_module, "settings", type("S", (), {"MEDIA_DIR": tmp_path})()
    )


def test_extract_pdf_markdown_keeps_figure_and_filters_noise(tmp_path, monkeypatch):
    pdf = tmp_path / "fig.pdf"
    _make_text_pdf_with_images(pdf, FIGURE_TEXT)
    _patch_media_dir(monkeypatch, tmp_path)

    markdown = extract_pdf_markdown(pdf, "task-1")

    # 只有正常插图被注入,水印与小图标被过滤。
    assert markdown.count("![试卷插图](") == 1
    assert "/static/media/task-1/pdf_p1_1.png" in markdown
    # 文本层完整保留(与 extract_pdf_text 去掉图片 token 后一致)。
    import re

    text_only = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)
    text_only = re.sub(r"\n{2,}", "\n", text_only).strip()
    assert text_only == extract_pdf_text(pdf).strip()
    # 插图字节已落盘,URL 可解析回真实文件。
    media_file = tmp_path / "task-1" / "pdf_p1_1.png"
    assert media_file.exists()
    assert media_file.read_bytes().startswith(b"\x89PNG")


def test_extract_pdf_markdown_without_images_matches_text(tmp_path, monkeypatch):
    pdf = tmp_path / "tags.pdf"
    _make_text_pdf(pdf, TAG_TEXT)
    _patch_media_dir(monkeypatch, tmp_path)

    assert extract_pdf_markdown(pdf, "task-2") == extract_pdf_text(pdf)


async def test_process_pdf_text_layer_keeps_figure_in_question_content(
    tmp_path, db_session, monkeypatch
):
    pdf = tmp_path / "fig.pdf"
    _make_text_pdf_with_images(pdf, FIGURE_TEXT)
    _patch_media_dir(monkeypatch, tmp_path)

    result = await pdf_processor.process_pdf(
        pdf, db_session, filename="fig.pdf", method="structured"
    )

    assert len(result["questions"]) == 1
    assert "![试卷插图](" in result["questions"][0]["content"]
