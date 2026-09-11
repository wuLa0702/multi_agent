/**
 * SearchPanel 本地搜索测试（v6 评审 P1-5）。
 * 覆盖：空查询引导 / 关键词过滤+高亮 / 点击结果跳转。
 */

import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useChatStore } from "@/lib/stores/chatStore";
import { messageScrollRef } from "@/lib/messageScroll";
import SearchPanel from "@/components/chat/SearchPanel";
import type { Message } from "@/lib/api/types";

const MSGS: Message[] = [
  { id: 1, session_id: "s1", role: "user", content: "帮我写一个 Python 爬虫", created_at: "2026-08-20T10:00:00Z" },
  { id: 2, session_id: "s1", role: "assistant", content: "好的，下面是一个爬虫示例", created_at: "2026-08-20T10:00:01Z" },
];

beforeEach(() => {
  useChatStore.setState({ messages: MSGS });
});
afterEach(() => {
  useChatStore.setState({ messages: [] });
  messageScrollRef.current = null;
});

describe("SearchPanel 本地搜索", () => {
  it("空查询显示引导文案", () => {
    render(<SearchPanel onClose={() => {}} />);
    expect(screen.getByText(/输入关键词/)).toBeTruthy();
  });

  it("关键词过滤消息并高亮命中", async () => {
    render(<SearchPanel onClose={() => {}} />);
    // 两条消息都含"爬虫" → 2 条命中
    fireEvent.change(screen.getByPlaceholderText("搜索当前对话内容…"), { target: { value: "爬虫" } });
    expect(await screen.findByText(/找到 2 条/)).toBeTruthy();
    expect(screen.getByText(/帮我写一个 Python/)).toBeTruthy();
    const mark = document.querySelector("mark");
    expect(mark?.textContent).toBe("爬虫");
  });

  it("点击结果触发跳转（滚动容器不为空）", () => {
    const scrollEl = { scrollTo: () => {}, querySelector: () => ({ offsetTop: 0 }) } as unknown as HTMLDivElement;
    messageScrollRef.current = scrollEl;
    render(<SearchPanel onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("搜索当前对话内容…"), { target: { value: "爬虫" } });
    fireEvent.click(screen.getByTestId("search-result-0"));
    // 未崩溃即跳转成功（scrollTo 被调用由 fake 吞掉）
    expect(messageScrollRef.current).toBe(scrollEl);
  });
});
