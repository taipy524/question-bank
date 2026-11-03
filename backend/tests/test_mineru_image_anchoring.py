"""MinerU 图片锚定(P2)与告警(P1)单测。

规则:试卷区 + 唯一题号区段 + 图片前的引用线索才锚定;答案区、无引用线索、
题号结构不足、答案标记之后的图片一律不挂,并产生可见告警。
"""

import io
import uuid
import zipfile

import pytest

from app.core.config import settings
from app.schemas.ai import AIQuestion
from app.services.importing.extract import AIExtractor
from app.services.importing.image_mask import mask_images
from app.services.importing.mineru_ingest import (
    MinerUIngestor,
    anchor_mineru_images,
    anchoring_warnings,
)

MEDIA_ID = "anchor-task"


def _task_id() -> str:
    return f"anchor-unit-{uuid.uuid4().hex[:8]}"


def _png_bytes(size=(120, 120), color=255) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("L", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _media_dir(tmp_path, files: dict[str, object]):
    """写入媒体文件。

    - 值为 ``(width, height)`` / ``(width, height, color)`` 元组时生成有效 PNG;
    - 值不是有效 PNG 字节时也生成有效 PNG(各测试的"占位字节"不再触发 unreadable);
    - 需要测试"损坏文件"时请直接写文件,不要走本函数。
    """
    base = tmp_path / MEDIA_ID
    for name, data in files.items():
        if isinstance(data, tuple):
            if len(data) == 2:
                data = _png_bytes(size=data)
            else:
                data = _png_bytes(size=data[:2], color=data[2])
        elif not (isinstance(data, bytes) and data.startswith(b"\x89PNG")):
            data = _png_bytes()
        path = base / "images" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return base


def _url(name: str) -> str:
    return f"/static/media/{MEDIA_ID}/images/{name}"


def _md(*segments: str) -> str:
    return "\n\n".join(segments) + "\n"


def test_figure_inside_question_is_anchored(tmp_path):
    media = _media_dir(tmp_path, {"a.png": b"a"})
    markdown = _md(
        "1. (3 分)如图，已知三角形 ABC，求面积。",
        f"![]({_url('a.png')})",
        "2. (3 分)下列说法正确的是（ ）",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/a.png"}]
    assert report["unresolved"] == []
    assert report["missing_figure_questions"] == []
    assert _url("a.png") in out
    assert anchoring_warnings(report) == []


def test_next_question_image_without_cue_is_not_anchored(tmp_path):
    """图片落在"没有如图线索"的下一题区段内时,不得挂给该题。"""
    media = _media_dir(tmp_path, {"b.png": b"b"})
    markdown = _md(
        "1. (3 分)如图，已知三角形 ABC。",
        "2. (3 分)下列说法正确的是（ ）",
        f"![]({_url('b.png')})",
        "3. (3 分)下一题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == []
    assert report["unresolved"] == [
        {"image": "images/b.png", "reason": "no_figure_reference", "question": 2}
    ]
    assert _url("b.png") not in out
    assert "image_unresolved:no_figure_reference:1" in anchoring_warnings(report)


def test_answer_region_images_are_not_anchored(tmp_path):
    media = _media_dir(tmp_path, {"exam.png": b"e", "answer.png": b"a"})
    markdown = _md(
        "1. (3 分)如图，已知三角形 ABC。",
        f"![]({_url('exam.png')})",
        "2. (3 分)下一题。",
        "## 参考答案与试题解析",
        "1. (3 分)如图，已知三角形 ABC。",
        f"![]({_url('answer.png')})",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/exam.png"}]
    assert {"image": "images/answer.png", "reason": "answer_region"} in report["unresolved"]
    assert _url("answer.png") not in out
    assert _url("exam.png") in out


def test_orphan_image_before_first_question_is_unresolved(tmp_path):
    media = _media_dir(tmp_path, {"cover.png": b"c"})
    markdown = _md(
        f"![]({_url('cover.png')})",
        "1. (3 分)如图，已知三角形 ABC。",
        "2. (3 分)下一题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["unresolved"] == [
        {"image": "images/cover.png", "reason": "outside_question"}
    ]
    assert _url("cover.png") not in out


def test_image_after_answer_marker_is_unresolved(tmp_path):
    """【答案】之后的图片无法区分题干图/解析图,保留未解决而不是错挂。"""
    media = _media_dir(tmp_path, {"a.png": b"a"})
    markdown = _md(
        "1. (3 分)如图，已知三角形 ABC。",
        "【答案】A",
        f"![]({_url('a.png')})",
        "2. (3 分)下一题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["unresolved"] == [
        {"image": "images/a.png", "reason": "after_answer_marker", "question": 1}
    ]
    assert _url("a.png") not in out
    assert "image_unresolved:after_answer_marker:1" in anchoring_warnings(report)


def test_weak_question_structure_skips_anchoring_and_keeps_images(tmp_path):
    """题号结构不足(只有一个题号)时不做锚定,也不清空图片。"""
    media = _media_dir(tmp_path, {"a.png": b"a"})
    markdown = _md("1. (3 分)如图，已知三角形 ABC。", f"![]({_url('a.png')})")

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["detected_questions"] == 0
    assert report["skipped_reason"] == "no_question_structure"
    assert report["unresolved"] == []
    assert _url("a.png") in out
    assert "image_anchoring_skipped:no_question_structure" in anchoring_warnings(report)


def test_tag_format_questions_are_anchored(tmp_path):
    """标签精准解析格式(【题目】分段)同样按区段锚定图片。"""
    media = _media_dir(tmp_path, {"a.png": b"a", "b.png": b"b"})
    markdown = _md(
        "【题目】如图，第一题。\n【选项】A. 甲  B. 乙",
        f"![]({_url('a.png')})",
        "【题目】第二题，没有图。",
        f"![]({_url('b.png')})",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/a.png"}]
    assert report["unresolved"] == [
        {"image": "images/b.png", "reason": "no_figure_reference", "question": 2}
    ]
    assert _url("a.png") in out and _url("b.png") not in out


def test_duplicate_bytes_reuse_media_and_keep_all_refs(tmp_path):
    """字节相同的两张图复用同一媒体文件,但两个引用都保留。"""
    media = _media_dir(tmp_path, {"a.png": b"same-bytes", "b.png": b"same-bytes"})
    markdown = _md(
        "1. (3 分)如图，第一题。",
        f"![]({_url('a.png')})",
        "2. (3 分)如图，第二题。",
        f"![]({_url('b.png')})",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [
        {"question": 1, "image": "images/a.png"},
        {"question": 2, "image": "images/b.png"},
    ]
    assert report["deduped"] == [{"image": "images/b.png", "canonical": "images/a.png"}]
    # 两个引用都在(去重只重写 URL,不删引用),且都指向同一个文件。
    assert out.count("![") == 2
    assert out.count(_url("a.png")) == 2
    assert _url("b.png") not in out
    assert (media / "images" / "a.png").exists()
    assert not (media / "images" / "b.png").exists()
    assert "image_deduped:1" in anchoring_warnings(report)


def test_missing_media_is_unresolved_and_not_referenced(tmp_path):
    """媒体文件不存在时移除引用,避免"图片已保留但引用断裂"。"""
    media = _media_dir(tmp_path, {})
    markdown = _md(
        "1. (3 分)如图，第一题。",
        f"![]({_url('ghost.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["unresolved"] == [
        {"image": "images/ghost.png", "reason": "missing_media", "question": 1}
    ]
    assert _url("ghost.png") not in out
    assert "image_unresolved:missing_media:1" in anchoring_warnings(report)


def test_anchored_markdown_stays_maskable(tmp_path):
    media = _media_dir(tmp_path, {"a.png": b"a"})
    markdown = _md(
        "1. (3 分)如图，第一题。",
        f"![]({_url('a.png')})",
        "2. (3 分)第二题。",
    )

    out, _ = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)
    masked, mapping = mask_images(out)

    assert len(mapping) == 1
    assert "@@IMG0@@" in masked


class _FakeClient:
    tier = "standard"

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def parse_zip(self, file_path):
        return self._payload, "task-x"


async def test_ingest_puts_anchoring_report_into_parse_meta(tmp_path):
    task_id = _task_id()
    markdown = _md(
        "1. (3 分)如图，第一题。",
        "![](images/a.png)",
        "2. (3 分)第二题。",
        "![](images/b.png)",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("markdown.md", markdown)
        archive.writestr("images/a.png", _png_bytes())
        archive.writestr("images/b.png", _png_bytes())
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    try:
        result, meta = await MinerUIngestor(client=_FakeClient(buffer.getvalue())).ingest(
            pdf, task_id=task_id
        )
    finally:
        for base in (settings.UPLOAD_DIR / task_id, settings.MEDIA_DIR / task_id):
            import shutil

            shutil.rmtree(base, ignore_errors=True)

    assert meta["engine"] == "mineru"
    assert meta["image_anchoring"]["anchored"] == [{"question": 1, "image": "images/a.png"}]
    assert meta["image_anchoring"]["unresolved"] == [
        {"image": "images/b.png", "reason": "no_figure_reference", "question": 2}
    ]
    assert "image_unresolved:no_figure_reference:1" in meta["warnings"]
    assert "manual_review:image_anchoring" in meta["warnings"]
    assert f"/static/media/{task_id}/images/a.png" in result
    assert f"/static/media/{task_id}/images/b.png" not in result


def test_restore_images_reports_unused_placeholders_as_warnings():
    mapping = {"@@IMG0@@": "![a](/static/media/t/a.png)", "@@IMG1@@": "![b](/static/media/t/b.png)"}
    questions = [
        AIQuestion(q_type="single_choice", content="题干 @@IMG0@@", options=["A. 1", "B. 2"])
    ]

    restored, warnings = AIExtractor._restore_images(questions, mapping)

    assert warnings == ["image_placeholder_unused:1"]
    assert "/static/media/t/a.png" in restored[0].content
    assert "@@IMG" not in (restored[0].content or "")

def test_figure_question_without_image_is_warned(tmp_path):
    """题干有"如图"但没有任何图片时,按题号告警(不挂图)。"""
    media = _media_dir(tmp_path, {})
    markdown = _md(
        "1. (3 分)如图，这题缺图。",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["missing_figure_questions"] == [1]
    assert report["answer_candidates"] == []
    warnings = anchoring_warnings(report)
    assert "image_missing_for_figure_question:1" in warnings
    assert "manual_review:image_anchoring" in warnings
    assert "![" not in out


def test_answer_region_image_is_only_a_candidate(tmp_path):
    """缺图题的答案区同题号图片只作候选告警,不自动挂图。"""
    media = _media_dir(tmp_path, {"ans.png": b"a"})
    markdown = _md(
        "1. (3 分)如图，这题缺图。",
        "2. (3 分)第二题。",
        "## 参考答案与试题解析",
        "1. (3 分)如图，这题缺图。",
        f"![]({_url('ans.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["missing_figure_questions"] == [1]
    assert report["answer_candidates"] == [
        {"question": 1, "images": ["images/ans.png"]}
    ]
    assert report["anchored"] == []
    assert _url("ans.png") not in out
    warnings = anchoring_warnings(report)
    assert "image_candidate_for_question:1:images/ans.png" in warnings
    assert "image_missing_for_figure_question:1" in warnings

def _real_image(path, size, dark_ratio=0.03):
    from PIL import Image, ImageDraw

    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    if dark_ratio >= 0.3:
        block = size[0] // 2
        for y in range(0, size[1], block):
            for x in range(0, size[0], block):
                if (x // block + y // block) % 2 == 0:
                    draw.rectangle([x, y, x + block - 1, y + block - 1], fill=0)
    else:
        draw.rectangle([1, size[1] // 3, size[0] - 2, size[1] // 3 + 1], fill=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_degenerate_small_image_is_not_anchored(tmp_path):
    """源文件把图压成极小框时,MinerU 只能裁出不可读小图 → 不挂,只告警。"""
    media = tmp_path / MEDIA_ID
    _real_image(media / "images" / "tiny.png", (77, 43))
    markdown = _md(
        "1. (3 分)如图，这题缺图。",
        f"![]({_url('tiny.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == []
    assert report["unresolved"] == [
        {"image": "images/tiny.png", "reason": "degenerate_image", "question": 1}
    ]
    assert report["missing_figure_questions"] == [1]
    warnings = anchoring_warnings(report)
    assert "image_unresolved:degenerate_image:1" in warnings
    assert "image_missing_for_figure_question:1" in warnings
    assert _url("tiny.png") not in out


def test_dark_filled_figure_is_kept(tmp_path):
    """深色/大填充面积的几何图是正常插图,不因暗度被丢弃。"""
    media = tmp_path / MEDIA_ID
    _real_image(media / "images" / "dark.png", (401, 398), dark_ratio=0.5)
    markdown = _md(
        "1. (3 分)如图，深色几何图。",
        f"![]({_url('dark.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/dark.png"}]
    assert report["unresolved"] == []
    assert _url("dark.png") in out


def test_normal_size_line_art_is_kept(tmp_path):
    """正常尺寸线稿不受退化判定影响。"""
    media = tmp_path / MEDIA_ID
    _real_image(media / "images" / "fig.png", (320, 220))
    markdown = _md(
        "1. (3 分)如图，正常配图。",
        f"![]({_url('fig.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/fig.png"}]
    assert report["unresolved"] == []
    assert _url("fig.png") in out

def _doc_with_cue(number: int, cue: str) -> str:
    segments = []
    for index in range(1, number + 1):
        text = f"{cue}，第 {index} 题。" if index == number else f"第 {index} 题。"
        segments.append(f"{index}. (3 分){text}")
        if index == number:
            segments.append(f"![]({_url('a.png')})")
    segments.append(f"{number + 1}. (3 分)下一题。")
    return _md(*segments)


@pytest.mark.parametrize(
    "number,cue",
    [
        (1, "如图"),
        (1, "如图4"),
        (1, "如下图"),
        (1, "见图"),
        (1, "图4"),
        (1, "附图"),
        (1, "如题1图"),
        (1, "如题 1 图"),
        (1, "题1图"),
        (1, "第1题图"),
        (4, "如题4图"),
        (4, "如题 4 图"),
        (8, "如题8图"),
        (13, "如题13图"),
    ],
)
def test_common_figure_cues_are_recognized(tmp_path, number, cue):
    media = _media_dir(tmp_path, {"a.png": (120, 120)})
    markdown = _doc_with_cue(number, cue)

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": number, "image": "images/a.png"}], report
    assert report["unresolved"] == []
    assert _url("a.png") in out


@pytest.mark.parametrize(
    "text",
    [
        "图形中的对称性",
        "图书馆有 3 层",
        "地图上的比例尺",
        "地图中的比例尺",
        "版图中的边界划分",
    ],
)
def test_non_figure_text_is_not_a_cue(tmp_path, text):
    media = _media_dir(tmp_path, {"a.png": (120, 120)})
    markdown = _md(f"1. (3 分){text}。", f"![]({_url('a.png')})", "2. (3 分)第二题。")

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == []
    assert report["unresolved"] == [
        {"image": "images/a.png", "reason": "no_figure_reference", "question": 1}
    ]
    assert _url("a.png") not in out


def test_cue_question_mismatch_is_not_anchored(tmp_path):
    """「如题4图」出现在第 2 题区段内时,不得挂到第 2 题。"""
    media = _media_dir(tmp_path, {"a.png": (120, 120)})
    markdown = _md(
        "1. (3 分)第一题。",
        "2. (3 分)如题4图，第二题。",
        f"![]({_url('a.png')})",
        "3. (3 分)第三题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == []
    assert report["unresolved"] == [
        {
            "image": "images/a.png",
            "reason": "cue_question_mismatch",
            "question": 2,
            "cue_question": 4,
        }
    ]
    assert _url("a.png") not in out
    assert "image_unresolved:cue_question_mismatch:1" in anchoring_warnings(report)


@pytest.mark.parametrize("size", [(100, 144), (138, 141)])
def test_small_but_real_figures_are_kept(tmp_path, size):
    media = tmp_path / MEDIA_ID
    _real_image(media / "images" / "small.png", size)
    markdown = _md(
        "1. (3 分)如图，小尺寸真实图。",
        f"![]({_url('small.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/small.png"}]
    assert report["unresolved"] == []


def test_unreadable_image_is_unresolved(tmp_path):
    media = tmp_path / MEDIA_ID
    broken = media / "images" / "broken.png"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not-an-image")
    markdown = _md(
        "1. (3 分)如图，损坏图。",
        f"![]({_url('broken.png')})",
        "2. (3 分)第二题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["unresolved"] == [
        {"image": "images/broken.png", "reason": "unreadable_image", "question": 1}
    ]
    assert _url("broken.png") not in out
    assert "image_unresolved:unreadable_image:1" in anchoring_warnings(report)


def test_report_records_cue_types_and_stats(tmp_path):
    media = _media_dir(tmp_path, {"a.png": (120, 120), "b.png": (120, 120)})
    markdown = _md(
        "1. (3 分)如题1图，第一题。",
        f"![]({_url('a.png')})",
        "2. (3 分)第二题。",
        f"![]({_url('b.png')})",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["cue_types"] == {"ru_ti": 1}
    assert report["stats"]["images_seen"] == 2
    assert report["stats"]["anchored"] == 1
    assert report["stats"]["unresolved"] == 1
    assert report["stats"]["by_reason"] == {"no_figure_reference": 1}
    assert report["stats"]["cue_types"] == {"ru_ti": 1}
    assert report["cue_strength"] == {"strong": 1}
    assert report["stats"]["cue_strength"] == {"strong": 1}

@pytest.mark.parametrize(
    "text",
    [
        "图中阴影部分的面积是",
        "图中点 A、B、C 共线",
        "求图中阴影部分的面积",
        "如图所示，求阴影面积",
    ],
)
def test_weak_figure_cues_are_recognized(tmp_path, text):
    """无明确题号但语义指向图形的表述,作为弱线索参与锚定(仍受题目边界约束)。"""
    media = _media_dir(tmp_path, {"a.png": (120, 120)})
    markdown = _md(f"1. (3 分){text}。", f"![]({_url('a.png')})", "2. (3 分)第二题。")

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [{"question": 1, "image": "images/a.png"}]
    assert report["unresolved"] == []
    assert report["cue_strength"] == {"weak": 1}
    assert report["cue_types"], "应记录线索分类"
    assert _url("a.png") in out


def test_weak_cue_does_not_cross_question_boundary(tmp_path):
    """弱线索只对其所在题段生效:图片在下一题段时既不挂上一题,也不挂下一题。"""
    media = _media_dir(tmp_path, {"a.png": (120, 120)})
    markdown = _md(
        "1. (3 分)图中阴影部分的面积是。",
        "2. (3 分)第二题。",
        f"![]({_url('a.png')})",
        "3. (3 分)第三题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == []
    assert report["unresolved"] == [
        {"image": "images/a.png", "reason": "no_figure_reference", "question": 2}
    ]
    # 第 1 题有引用但没图 → 可见告警;第 2 题图片无引用 → 未解决
    assert report["missing_figure_questions"] == [1]
    assert _url("a.png") not in out


def test_pure_image_options_are_attached_to_their_labels(tmp_path):
    media = _media_dir(
        tmp_path,
        {
            "a.png": (120, 120, 20),
            "b.png": (120, 120, 60),
            "c.png": (120, 120, 120),
            "d.png": (120, 120, 200),
        },
    )
    markdown = _md(
        "1. (3 分)下列图形中，是轴对称图形的是（ ）。",
        "A.\nB.\nC.\nD.",
        f"![]({_url('a.png')})",
        f"![]({_url('b.png')})",
        f"![]({_url('c.png')})",
        f"![]({_url('d.png')})",
        "2. (3 分)下列说法正确的是（ ）。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["option_images"] == [
        {"question": 1, "option": "A", "image": "images/a.png"},
        {"question": 1, "option": "B", "image": "images/b.png"},
        {"question": 1, "option": "C", "image": "images/c.png"},
        {"question": 1, "option": "D", "image": "images/d.png"},
    ]
    assert report["unresolved"] == []
    assert report["anchored"] == []
    assert report["missing_figure_questions"] == []
    for label, name in zip("ABCD", ("a", "b", "c", "d")):
        assert f"{label}.![]({_url(name + '.png')})" in out
    positions = [out.index(f"{label}.![](") for label in "ABCD"]
    assert positions == sorted(positions)
    assert anchoring_warnings(report) == []


def test_text_options_do_not_move_images(tmp_path):
    media = _media_dir(tmp_path, {"a.png": b"a"})
    markdown = _md(
        "1. (3 分)下列图形中，是轴对称图形的是（ ）。",
        "A. 三角形\nB. 正方形\nC. 圆\nD. 平行四边形",
        f"![]({_url('a.png')})",
        "2. (3 分)下列说法正确的是（ ）。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["option_images"] == []
    assert _url("a.png") not in out, "图片不得被挂到 A/B/C/D 标签后"
    assert {"image": "images/a.png", "reason": "no_figure_reference", "question": 1} in report["unresolved"]


def test_hyphenated_figure_numbers_are_recognized_as_cues(tmp_path):
    media = _media_dir(
        tmp_path, {"p1.png": (120, 120, 20), "p2.png": (120, 120, 200)}
    )
    markdown = _md(
        "1. (3 分)如题 1-1 图所示，已知三角形 ABC，求面积。",
        f"![]({_url('p1.png')})",
        "随后按如题1-2图的方式折叠，求重叠部分面积。",
        f"![]({_url('p2.png')})",
        "2. (3 分)下一题。",
    )

    out, report = anchor_mineru_images(markdown, media_dir=media, media_id=MEDIA_ID)

    assert report["anchored"] == [
        {"question": 1, "image": "images/p1.png"},
        {"question": 1, "image": "images/p2.png"},
    ]
    assert report["unresolved"] == []
    assert report["cue_strength"] == {"strong": 2}
    assert _url("p1.png") in out and _url("p2.png") in out
