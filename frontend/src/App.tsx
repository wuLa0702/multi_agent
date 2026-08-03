/**
 * 应用入口 — 单页（ChatPage），无独立路由。
 * 设计 §2：历史在侧栏内完成，不做独立 HistoryPage（MVP 减负）。
 */

import ChatPage from "@/pages/ChatPage";

export default function App() {
  return <ChatPage />;
}
