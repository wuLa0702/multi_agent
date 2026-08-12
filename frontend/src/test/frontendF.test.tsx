/**
 * F1/F2/F3 前端补充单测（2026-08-12）。
 * - api mock 分支：updateModelPrice / getCostSummary / getCostAlerts / listProviders(含单价) / getSettings
 * - 组件：ModelPriceList（单价行渲染）/ CostPanel（成本汇总展示）
 * mock.ts MOCK_ENABLED=true 全局生效，api 方法直接返回 mock 数据。
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { api } from "@/lib/api/client";
import { ModelPriceList } from "@/components/settings/ModelPriceList";
import { CostPanel } from "@/components/chat/CostPanel";

describe("F1 模型单价 api mock", () => {
  it("updateModelPrice 返回 ok", async () => {
    const r = await api.updateModelPrice(1, 0.001, 0.002);
    expect(r.status).toBe("ok");
  });

  it("listProviders 含单价字段", async () => {
    const p = await api.listProviders();
    expect(p.providers.length).toBeGreaterThan(0);
    expect(p.providers[0].models[0].input_price).toBeDefined();
  });

  it("ModelPriceList 渲染模型单价行", async () => {
    render(<ModelPriceList />);
    expect(await screen.findByTestId("model-price-list")).toBeTruthy();
    // mock deepseek 模型行出现（异步加载）
    expect(await screen.findByText(/deepseek-v4-flash/)).toBeTruthy();
  });
});

describe("F2 成本展示 api mock", () => {
  it("getCostSummary 返回汇总", async () => {
    const s = await api.getCostSummary("s1");
    expect(s.session_id).toBe("s1");
    expect(s.total_cost).toBeGreaterThan(0);
  });

  it("getCostAlerts 返回告警", async () => {
    const a = await api.getCostAlerts("s1");
    expect(a.items.length).toBeGreaterThan(0);
  });

  it("CostPanel 展示成本汇总", async () => {
    render(<CostPanel sessionId="s1" />);
    expect(await screen.findByText(/¥/)).toBeTruthy();
  });
});
