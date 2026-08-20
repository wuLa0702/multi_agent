/**
 * App — 三栏布局主框架（方案 §4.1：一级导航 64px + 二级栏 280px + 主内容区）。
 * 视图切换：对话 / 能力市场 / 设置，切换时内容交叉淡入（250ms）。
 */

import { useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import Sidebar from "@/components/layout/Sidebar";
import ChatPage from "@/pages/ChatPage";
import SkillsPage from "@/pages/SkillsPage";
import SettingsPage from "@/pages/SettingsPage";
import type { ViewKey } from "@/lib/navigation";

export default function App() {
  const [activeView, setActiveView] = useState<ViewKey>("chat");

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen overflow-hidden">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />

      {/* 视图切换：key 强制重挂载 → 触发 view-enter 动效（方案 §4.3.1） */}
      <div key={activeView} className="view-enter flex min-w-0 flex-1">
        {activeView === "chat" && <ChatPage />}
        {activeView === "skills" && <SkillsPage />}
        {activeView === "settings" && <SettingsPage />}
      </div>
      </div>
    </TooltipProvider>
  );
}
