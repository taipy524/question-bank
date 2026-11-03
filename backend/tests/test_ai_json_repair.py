"""AI 返回 JSON 的 LaTeX 反斜杠修复测试。

重点:不仅断言"能解析",还断言解析后的公式内容**完整**(反斜杠未被吞成
制表符/换行/退格)。
"""

import sys
import types
from types import SimpleNamespace

import pytest

from app.services.ai_provider import (
    AIProviderUnavailableError,
    AIResponseFormatError,
    OpenAIProvider,
    parse_questions_payload,
    repair_json_latex_escapes,
)


def _content_of(question) -> str:
    return question.content


def test_normal_wrapped_json():
    payload = '{"questions":[{"q_type":"single_choice","content":"题干","answer":"A"}]}'
    questions = parse_questions_payload(payload)
    assert len(questions) == 1
    assert questions[0].content == "题干"


def test_bare_list_json():
    payload = '[{"q_type":"single_choice","content":"题干","answer":"A"}]'
    questions = parse_questions_payload(payload)
    assert len(questions) == 1
    assert questions[0].answer == "A"


def test_single_question_object():
    payload = '{"q_type":"fill_in_the_blank","content":"1+1=____","answer":[["2"]]}'
    questions = parse_questions_payload(payload)
    assert len(questions) == 1
    assert questions[0].content == "1+1=____"


def test_markdown_fence_is_tolerated():
    payload = '```json\n{"questions":[{"q_type":"single_choice","content":"题干"}]}\n```'
    questions = parse_questions_payload(payload)
    assert questions[0].content == "题干"


@pytest.mark.parametrize(
    "latex",
    [
        r"\frac{1}{2}",
        r"\theta",
        r"\begin{aligned}x=1\end{aligned}",
        r"\sqrt{2}",
        r"\text{面积}",
        r"\pi r^2",
        r"\alpha+\beta",
        r"\left( x \right)",
    ],
)
def test_latex_command_survives_intact(latex):
    """单个 LaTeX 命令:解析后内容必须与原文逐字一致(含单反斜杠)。"""
    payload = (
        '{"questions":[{"q_type":"single_choice","content":"$'
        + latex
        + '$","answer":"A"}]}'
    )
    questions = parse_questions_payload(payload)
    assert questions[0].content == f"${latex}$"


def test_multiple_latex_commands_together():
    payload = (
        r'{"questions":[{"q_type":"free_response",'
        r'"content":"设 $\frac{a}{b}$，且 $\theta\in(0,\pi)$，由 $\begin{cases}x=1\\y=2\end{cases}$ 得 $\sqrt{\alpha}$",'
        r'"answer":"A"}]}'
    )
    questions = parse_questions_payload(payload)
    content = _content_of(questions[0])
    for fragment in (
        r"$\frac{a}{b}$",
        r"$\theta\in(0,\pi)$",
        r"\begin{cases}",
        r"\end{cases}",
        r"$\sqrt{\alpha}$",
    ):
        assert fragment in content, content


def test_valid_json_escapes_are_not_broken():
    payload = (
        '{"questions":[{"q_type":"free_response",'
        '"content":"第一行\\n第二行 \\"引号\\" 反斜杠\\\\end \\u4e2d",'
        '"answer":"A"}]}'
    )
    questions = parse_questions_payload(payload)
    content = questions[0].content
    assert "第一行\n第二行" in content
    assert '"引号"' in content
    assert r"反斜杠\end" in content
    assert "中" in content


def test_invalid_escapes_are_escaped():
    payload = r'{"questions":[{"q_type":"single_choice","content":"$\sigma$ 与 $\partial$","answer":"A"}]}'
    questions = parse_questions_payload(payload)
    assert r"$\sigma$" in _content_of(questions[0])
    assert r"$\partial$" in _content_of(questions[0])


def test_newline_not_treated_as_latex_command():
    payload = '{"questions":[{"q_type":"free_response","content":"a\\nNew","answer":"A"}]}'
    questions = parse_questions_payload(payload)
    assert questions[0].content == "a\nNew"


def test_repair_is_idempotent():
    once = repair_json_latex_escapes(r'{"c":"\frac{1}{2} \theta"}')
    twice = repair_json_latex_escapes(once)
    assert once == twice
    assert r"\frac{1}{2}" in once and r"\theta" in once


def test_unrecoverable_payload_raises_format_error():
    with pytest.raises(AIResponseFormatError):
        parse_questions_payload('{"questions":[{"q_type":"single_choice","content":"x"}')


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content=None, error=None):
        self._content = content
        self._error = error

    async def create(self, **kwargs):
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content=None, error=None):
        self.completions = _FakeCompletions(content, error)


class _FakeAsyncOpenAI:
    def __init__(self, content=None, error=None):
        self.chat = _FakeChat(content, error)


def _install_fake_openai(monkeypatch, content=None, error=None):
    module = types.ModuleType("openai")
    module.AsyncOpenAI = lambda *args, **kwargs: _FakeAsyncOpenAI(content, error)
    monkeypatch.setitem(sys.modules, "openai", module)


def _config():
    return {"API_KEY": "test-key", "MODEL_NAME": "test-model", "AI_EXTRACT_PROMPT": "{content}"}


async def test_provider_extracts_latex_payload(monkeypatch):
    bad_json = r'{"questions":[{"q_type":"single_choice","content":"$\frac{1}{2}$ 与 $\theta$","options":["A. $\sqrt{2}$","B. $\pi$"],"answer":"A"}]}'
    _install_fake_openai(monkeypatch, content=bad_json)

    questions = await OpenAIProvider().extract_questions("md", None, _config())

    assert len(questions) == 1
    assert r"$\frac{1}{2}$" in questions[0].content
    assert r"$\theta$" in questions[0].content
    assert r"$\sqrt{2}$" in (questions[0].options or [])[0]


async def test_provider_maps_dns_error_to_unavailable(monkeypatch):
    import socket

    _install_fake_openai(monkeypatch, error=socket.gaierror(-5, "No address associated with hostname"))

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        await OpenAIProvider().extract_questions("md", None, _config())
    assert "DNS" in str(excinfo.value)
    assert "test-key" not in str(excinfo.value)


async def test_provider_maps_connect_error_to_unavailable(monkeypatch):
    import httpx

    _install_fake_openai(monkeypatch, error=httpx.ConnectError("boom"))

    with pytest.raises(AIProviderUnavailableError) as excinfo:
        await OpenAIProvider().extract_questions("md", None, _config())
    assert "网络" in str(excinfo.value) or "DNS" in str(excinfo.value)
    assert "test-key" not in str(excinfo.value)

class _CapturingCompletions:
    def __init__(self, content):
        self._content = content
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponse(self._content)


async def test_system_prompt_requires_strict_json_and_escaped_latex(monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, *args, **kwargs):
            completions = _CapturingCompletions('{"questions":[]}')
            captured["completions"] = completions
            self.chat = SimpleNamespace(completions=completions)

    module = types.ModuleType("openai")
    module.AsyncOpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", module)

    await OpenAIProvider().extract_questions("md", None, _config())

    system_prompt = captured["completions"].kwargs["messages"][0]["content"]
    assert "JSON 输出约束" in system_prompt
    assert "两个反斜杠" in system_prompt
    assert "代码围栏" in system_prompt
