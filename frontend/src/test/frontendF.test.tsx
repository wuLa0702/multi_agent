/**
 * F1/F2/F3 前端补充单测（2026-08-12）。
 * - api 方法：updateModelPrice / getCostSummary / getCostAlerts / listProviders(含单价) / getSettings
 * - 组件：ModelPriceList（单价行渲染）/ CostPanel（成本汇总展示）
 * MOCK_ENABLED=false（真后端模式）→ 本测试用 fetch stub 模拟后端响应，测试不依赖后端。
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { api } from "@/lib/api/client";
import { ModelPriceList } from "@/components/settings/ModelPriceList";
import { CostPanel } from "@/components/chat/CostPanel";

// fetch stub：按 URL 路由返回模拟后端数据（MOCK_ENABLED=false 时 api 走真 fetch）
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const u = String(input);
      let body: unknown = { status: "ok" };
      if (u.includes("/v1/providers/models/") && u.includes("/price")) {
        body = { status: "ok", model_id: 1 };
      } else if (u.includes("/v1/providers")) {
        body = {
          providers: [
            { id: 1, slug: "deepseek", name: "DeepSeek", is_active: true,
              models: [{ id: 1, provider_id: 1, name: "deepseek-v4-flash", is_default: true, is_active: true, input_price: 0.001, output_price: 0.002 }] },
          ],
        };
      } else if (u.includes("/v1/cost/summary")) {
        body = { session_id: "s1", total_cost: 1.2345, input_tokens: 12000, output_tokens: 3000, alert_count: 1 };
      } else if (u.includes("/v1/cost/alerts")) {
        body = { status: "ok", items: [{ threshold: 1, total_cost: 1.23, created_at: "2026-08-12" }], total: 1 };
      } else if (u.includes("/v1/settings")) {
        body = { status: "ok", settings: { hitl_enabled: "true" } };
      }
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
});

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
