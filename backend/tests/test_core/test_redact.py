"""出站脱敏单测（阶段 3，2026-10-15）：纯函数规则表 + 反例 + 中间件接线。

设计见 `docs/决策/2026-10-15-设计-阶段3横切与阶段4编排-v1.md` §3。
规则范围由 co-creator 拍板：密钥 / 手机号 / 邮箱 / 身份证；
**不含内网 IP、不含绝对路径**（路径是任务上下文，脱了模型看不懂）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from src.core.config import settings
from src.llm.redact import RedactMiddleware, redact, redact_message_content


class TestRedactRules:
    """规则表逐条：该脱的脱掉，且计数正确。"""

    @pytest.mark.parametrize(
        ("text", "label"),
        [
            ("key=sk-abcdefghijklmnop1234", "KEY"),
            ("AKIAIOSFODNN7EXAMPLE", "KEY"),
            ("Authorization: Bearer abcdef123456xyz", "KEY"),
            ("联系我 13800138000 谢谢", "PHONE"),
            ("邮箱 user.name+tag@example.com 收", "EMAIL"),
            ("身份证 110101199003071234 请核", "ID"),
        ],
    )
    def test_each_rule_masks(self, text: str, label: str) -> None:
        out, hits = redact(text)
        assert hits.get(label) == 1, f"{label} 未命中：{out}"
        assert f"[已脱敏:{label}]" in out
        assert text != out

    def test_mixed_counts(self) -> None:
        """多类混合：计数按类别分别累加。"""
        out, hits = redact("a@b.com 13800138000 sk-abcdefghijklmnop1234 a@b.com")

        assert hits == {"KEY": 1, "PHONE": 1, "EMAIL": 2}
        assert "a@b.com" not in out and "13800138000" not in out

    def test_clean_text_untouched(self) -> None:
        """无敏感信息 → 原文不动、零计数。"""
        text = "请把《红楼梦》第一章总结成 300 字"
        assert redact(text) == (text, {})

    def test_idempotent(self) -> None:
        """幂等：重复脱敏结果稳定（掩码不含数字/@，不会互相吞噬）。"""
        once, _ = redact("sk-abcdefghijklmnop1234 与 13800138000")
        twice, hits = redact(once)

        assert twice == once
        assert hits == {}, "已脱敏文本不应再命中任何规则"


class TestNoFalsePositives:
    """反例：不误伤正常内容（误伤会静默改变模型看到的语义）。"""

    def test_non_mobile_11_digits(self) -> None:
        """11 位但非手机号段（非 1[3-9] 开头）不脱。"""
        text = "订单号 20123456789"
        assert redact(text) == (text, {})

    def test_longer_digit_run_not_split(self) -> None:
        """长数字串不被切碎成"手机号"——边界断言 `(?<!\\d)` / `(?!\\d)` 的作用。"""
        text = "流水号 991380013800099"
        out, hits = redact(text)

        assert hits == {}
        assert out == text

    def test_email_without_tld_untouched(self) -> None:
        """`user@localhost`（无顶级域）不脱。"""
        text = "user@localhost 是本机账号"
        assert redact(text) == (text, {})

    def test_private_ip_untouched(self) -> None:
        """内网 IP **不脱**（co-creator 2026-10-15 拍板：未纳入规则范围）。"""
        text = "内网 10.1.2.3 与 192.168.1.100 均为测试环境"
        assert redact(text) == (text, {})

    def test_absolute_paths_untouched(self) -> None:
        """绝对路径**不脱**：路径是任务上下文，脱了模型不知道在说哪个文件。"""
        for text in (r"打开 D:\projects\demo\secret.txt", "查看 /home/user/app/main.py"):
            assert redact(text) == (text, {})


class TestRedactMessageContent:
    """消息 content 形态：str 直脱；content-block 列表逐块脱 text。"""

    def test_str_content(self) -> None:
        out, hits = redact_message_content("手机 13800138000")
        assert hits == {"PHONE": 1}
        assert "13800138000" not in out

    def test_block_list_content(self) -> None:
        blocks = [
            {"type": "text", "text": "邮箱 a@b.com"},
            {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
        ]
        out, hits = redact_message_content(blocks)

        assert hits == {"EMAIL": 1}
        assert "a@b.com" not in out[0]["text"]
        assert out[1] == blocks[1], "非文本块原样保留"

    def test_unknown_shape_untouched(self) -> None:
        """非 str / 非 list（不认识的形态）原样返回，不猜结构。"""
        assert redact_message_content(123) == (123, {})


class _FakeModelRequest:
    """鸭子类型 ModelRequest（只含中间件用到的接口）。"""

    def __init__(self, messages: list) -> None:
        self.messages = messages

    def override(self, **overrides):  # noqa: ANN003
        return _FakeModelRequest(overrides.get("messages", self.messages))


class _CapturingHandler:
    """记录 handler 实际收到的消息（供断言"模型看到了什么"）。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, request):
        self.seen = [str(m.content) for m in request.messages]
        return SimpleNamespace(ok=True)


class TestRedactMiddleware:
    """中间件（主对话路径）：模型调用前脱敏，且旁路失败不阻断。"""

    async def test_redacts_before_model_call(self) -> None:
        """主路径核心断言：handler（= 模型调用）收到的是脱敏后文本。"""
        middleware = RedactMiddleware()
        handler = _CapturingHandler()
        request = _FakeModelRequest([HumanMessage(content="我的手机 13800138000")])

        await middleware.awrap_model_call(request, handler)

        assert "13800138000" not in handler.seen[0]
        assert "[已脱敏:PHONE]" in handler.seen[0]

    async def test_clean_messages_pass_through(self) -> None:
        """无敏感信息 → 不 override（零开销路径）。"""
        middleware = RedactMiddleware()
        handler = _CapturingHandler()
        original = _FakeModelRequest([HumanMessage(content="普通问题")])

        result = await middleware.awrap_model_call(original, handler)

        assert handler.seen == ["普通问题"]
        assert result.ok is True

    async def test_disabled_by_switch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """开关关掉 → 原样出站（便于对比排查）。"""
        monkeypatch.setattr(settings, "redact_enabled", False)
        middleware = RedactMiddleware()
        handler = _CapturingHandler()

        await middleware.awrap_model_call(
            _FakeModelRequest([HumanMessage(content="手机 13800138000")]), handler
        )

        assert "13800138000" in handler.seen[0]

    async def test_failure_does_not_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """脱敏自身炸了 → 按原文出站，绝不阻断对话（横切旁路纪律）。"""
        monkeypatch.setattr(
            "src.llm.redact.redact_message_content",
            lambda c: (_ for _ in ()).throw(RuntimeError("redact boom")),
        )
        middleware = RedactMiddleware()
        handler = _CapturingHandler()

        result = await middleware.awrap_model_call(
            _FakeModelRequest([HumanMessage(content="手机 13800138000")]), handler
        )

        assert result.ok is True, "脱敏失败不得阻断模型调用"
        assert handler.seen == ["手机 13800138000"], "按原文出站"
