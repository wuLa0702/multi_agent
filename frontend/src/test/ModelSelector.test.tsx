/**
 * ModelSelector 重构测试（v6 评审 P1-4，修 #11：模型标"默认"泛滥）。
 * 覆盖：当前模型显示 / 厂商分组+推荐徽标 / 搜索过滤。
 */

import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ModelSelector from "@/components/chat/ModelSelector";
import type { ProviderInfo } from "@/lib/api/types";

const PROVIDERS: ProviderInfo[] = [
  {
    id: 1,
    slug: "deepseek",
    name: "DeepSeek",
    is_active: true,
    models: [
      { id: 1, provider_id: 1, name: "deepseek-v4-flash", is_default: true, is_active: true },
      { id: 2, provider_id: 1, name: "deepseek-reasoner", is_default: false, is_active: true },
    ],
  },
  {
    id: 2,
    slug: "zhipu",
    name: "智谱",
    is_active: true,
    models: [{ id: 3, provider_id: 2, name: "glm-4", is_default: true, is_active: true }],
  },
];

describe("ModelSelector（P1-4 重构）", () => {
  it("触发按钮显示当前模型名", () => {
    render(<ModelSelector providers={PROVIDERS} selectedModelId={1} onSelect={() => {}} />);
    expect(screen.getByText("deepseek-v4-flash")).toBeTruthy();
  });

  it("展开按厂商分组 + 推荐徽标（替代每行默认标签）", () => {
    render(<ModelSelector providers={PROVIDERS} selectedModelId={1} onSelect={() => {}} />);
    fireEvent.click(screen.getByLabelText("选择模型"));
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText("智谱")).toBeTruthy();
    // 推荐徽标：每家厂商头按钮 + 默认模型行（≥2）
    expect(screen.getAllByText("推荐").length).toBeGreaterThanOrEqual(2);
  });

  it("搜索过滤模型名，无匹配的厂商分组隐藏", () => {
    render(<ModelSelector providers={PROVIDERS} selectedModelId={1} onSelect={() => {}} />);
    fireEvent.click(screen.getByLabelText("选择模型"));
    fireEvent.change(screen.getByLabelText("搜索模型"), { target: { value: "glm" } });
    expect(screen.getByText("glm-4")).toBeTruthy();
    expect(screen.queryByText("DeepSeek")).toBeNull();
  });
});
