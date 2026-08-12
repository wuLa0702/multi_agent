"""模型配置实体：providers / models 表的 Pydantic 模型。

分层（10-api.md：Pydantic v2，禁裸 dict）：
- ProviderInfo / ModelInfo / ProviderWithModels — 对外（GET /v1/providers）
- ModelConfig — 对内（adapter 构造 ChatOpenAI 的完整参数，含密钥来源名，
  绝不出 API）
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """模型条目（前端下拉二级选项）。"""

    id: int
    provider_id: int
    name: str = Field(description="模型名（API 透传标识，如 deepseek-v4-flash）")
    is_default: bool = Field(description="该 provider 的默认模型")
    is_active: bool


class ProviderInfo(BaseModel):
    """厂商条目（前端下拉一级选项）。"""

    id: int
    slug: str = Field(description="厂商标识（deepseek / ark / zhipu）")
    name: str = Field(description="厂商显示名（DeepSeek / 豆包 / 智谱）")
    is_active: bool


class ProviderWithModels(ProviderInfo):
    """厂商 + 其下模型列表（GET /v1/providers 响应单元）。"""

    models: list[ModelInfo]


class ProvidersResponse(BaseModel):
    """GET /v1/providers 响应。"""

    providers: list[ProviderWithModels]


class ModelConfig(BaseModel):
    """完整模型调用参数（内部用：registry → adapter，不暴露 API）。

    Attributes:
        id: models 表主键（请求 model_id）
        provider_slug: 厂商标识（查 API key 用）
        model_name: 模型名（ChatOpenAI model 参数）
        base_url: API 地址
        api_key_env: .env 变量名（如 DEEPSEEK_API_KEY，密钥不入库）
    """

    id: int
    provider_slug: str
    model_name: str
    base_url: str
    api_key_env: str
    input_price: float = 0.0   # 成本档位（元/千 token 输入，2026-08-11 成本控制）
    output_price: float = 0.0  # 成本档位（元/千 token 输出）
