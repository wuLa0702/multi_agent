/**
 * App 路由冒烟测试（v6 评审 P0-2 方案A：react-router 完整路由化）。
 * 验证：一级导航渲染、点击「设置」→ 路由切到 /settings 渲染设置页、点击「对话」返回。
 * fetch stub 404：页面挂载的数据请求全部降级，不依赖后端。
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import App from "@/App";

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

describe("App 路由化（方案A）", () => {
  it("一级导航渲染（对话/能力市场/设置）", () => {
    render(<App />);
    expect(screen.getByLabelText("对话")).toBeTruthy();
    expect(screen.getByLabelText("能力市场")).toBeTruthy();
    expect(screen.getByLabelText("设置")).toBeTruthy();
  });

  it("点击设置 → 路由到 /settings 渲染设置页", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("设置"));
    // 设置页「账户与密钥」出现（菜单 + 页面标题，用 AllBy 兼容多命中）
    expect((await screen.findAllByText("账户与密钥")).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe("/settings");
  });

  it("设置页 → 点击对话返回聊天页", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("设置"));
    await screen.findAllByText("账户与密钥");
    fireEvent.click(screen.getByLabelText("对话"));
    expect(window.location.pathname).toBe("/");
    // 聊天页出现（页头 + 会话栏各有一个「新建会话」按钮）
    expect((await screen.findAllByLabelText("新建会话")).length).toBeGreaterThan(0);
  });
});
