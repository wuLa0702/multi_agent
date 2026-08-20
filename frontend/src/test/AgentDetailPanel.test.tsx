/**
 * AgentDetailPanel 测试（v6 评审 P0-1：5列→4列布局重构）。
 * 覆盖：关闭态不渲染 / 展开态渲染标题+区块 / 关闭回调。
 * CostPanel 用 react-router → 包 MemoryRouter；fetch stub 404 避免真网络。
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AgentDetailPanel from "@/components/agent/AgentDetailPanel";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }) as Response),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("AgentDetailPanel（P0-1 合并 InfoPanel + AgentPanel）", () => {
  it("关闭态不渲染（默认关 → 3 列布局）", () => {
    const { container } = render(<AgentDetailPanel open={false} onClose={() => {}} />);
    expect(container.querySelector('[aria-label="Agent 详情面板"]')).toBeNull();
  });

  it("展开态渲染标题 + 合并的区块", () => {
    render(
      <MemoryRouter>
        <AgentDetailPanel open onClose={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Agent 详情")).toBeTruthy();
    expect(screen.getByLabelText("关闭面板")).toBeTruthy();
    // InfoPanel 迁移来的 3 区块
    expect(screen.getByText("任务进度")).toBeTruthy();
    expect(screen.getByText("成本 / 告警")).toBeTruthy();
    expect(screen.getByText("关联 Wiki")).toBeTruthy();
    // AgentPanel 迁移来的 2 区块
    expect(screen.getByText("工具调用")).toBeTruthy();
    expect(screen.getByText("Agent 调用链")).toBeTruthy();
  });

  it("点击关闭回调 onClose", () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <AgentDetailPanel open onClose={onClose} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByLabelText("关闭面板"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
