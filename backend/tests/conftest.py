"""共享 Fixture：mock LLM / tmp_path / :memory: 数据库。

约定（.claude/rules/20-testing.md）：
- LLM 全部 mock，不实际调 API
- 文件系统用 tmp_path，数据库用 :memory:
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# 确保 backend 可导入（src/ 是包，import src.core.config 需要 backend 在 path 上）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def app_env_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 APP_ENV=dev，避免测试误读 .env.prod。"""
    monkeypatch.setenv("APP_ENV", "dev")


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """临时数据目录（替代真实 data/，测试隔离）。"""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tmp_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 SQLite：settings.db_path 指向 tmp（chat 流落库测试用）。"""
    from src.core.config import settings

    p = tmp_path / "test.db"
    monkeypatch.setattr(settings, "db_path", str(p))
    return p


@pytest.fixture
def mock_llm_chat(mocker) -> None:
    """Mock LLMAdapter.chat 返回值（按需 override return_value）。"""
    mocker.patch("src.llm.adapter.LLMAdapter.chat", return_value="mock response")


class FakeDeepAgentModel(BaseChatModel):
    """deepagents 专用 fake 模型：支持 bind_tools + 流式（按字符吐 token）。

    真实 fake（FakeListChatModel/GenericFakeChatModel）不支持 bind_tools，
    deepagents 内部绑定 todo 工具时会炸——本项目测试统一用本类。
    responses 循环取用（多轮对话时按序返回）。
    """

    responses: list[str]
    _index: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-deepagent"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001 - 保持 BaseChatModel 签名
        """绑定工具：fake 直接返回自身（模型永不出工具调用）。"""
        return self

    async def _astream(self, messages, **kwargs):  # noqa: ANN001
        # langchain 1.x 契约：yield ChatGenerationChunk（message 为 AIMessageChunk）
        resp = self._next_response()
        for ch in resp:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=ch), generation_info={}
            )

    def _stream(self, messages, **kwargs):  # noqa: ANN001
        resp = self._next_response()
        for ch in resp:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=ch), generation_info={}
            )

    async def _agenerate(self, messages, **kwargs):  # noqa: ANN001
        resp = self._next_response()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=resp))])

    def _generate(self, messages, **kwargs):  # noqa: ANN001
        """langchain 1.x BaseChatModel 抽象方法（同步生成，供 sync 调用路径）。"""
        resp = self._next_response()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=resp))])

    def _next_response(self) -> str:
        resp = self.responses[self._index % len(self.responses)]
        self._index += 1
        return resp


@pytest.fixture
def fake_deep_agent_model() -> FakeDeepAgentModel:
    """deepagents 可用的 fake LLM（按字符流式，默认单条回复）。"""
    return FakeDeepAgentModel(responses=["你好，这是 mock 回复"])


@pytest.fixture
def mock_chat_llm(mocker, fake_deep_agent_model: FakeDeepAgentModel) -> FakeDeepAgentModel:
    """patch src.api.chat.get_chat_model → fake 模型（chat SSE 测试用）。"""
    mocker.patch("src.api.chat.get_chat_model", return_value=fake_deep_agent_model)
    return fake_deep_agent_model
