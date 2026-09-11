/**
 * App — 三栏布局主框架（方案 §4.1：一级导航 64px + 二级栏 280px + 主内容区）。
 * 视图切换：对话 / 能力市场 / 设置。v6 评审 P0-2 方案A：react-router 完整路由化——
 * BrowserRouter + Routes，三视图改路由路径（/、/skills、/settings），切换时内容交叉淡入（250ms）。
 */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import Sidebar from "@/components/layout/Sidebar";
import ChatPage from "@/pages/ChatPage";
import SkillsPage from "@/pages/SkillsPage";
import SettingsPage from "@/pages/SettingsPage";

function AppShell() {
  const { pathname } = useLocation();

  return (
    <TooltipProvider delay={300}>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />

        {/* 路由切换：key 强制重挂载 → 触发 view-enter 动效（方案 §4.3.1） */}
        <div key={pathname} className="view-enter flex min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </TooltipProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
