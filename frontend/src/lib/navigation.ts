/**
 * 一级导航视图定义（方案 §4.1：对话 / 能力市场 / 设置）+ 路由路径（v6 评审 P0-2 方案A）。
 * 单用户场景：预留记忆、监控、帮助。
 */

export type ViewKey = "chat" | "skills" | "settings";

export const VIEWS: { key: ViewKey; label: string }[] = [
  { key: "chat", label: "对话" },
  { key: "skills", label: "能力市场" },
  { key: "settings", label: "设置" },
];

/** ViewKey → 路由路径（react-router 方案A：/、/skills、/settings） */
export const VIEW_PATHS: Record<ViewKey, string> = {
  chat: "/",
  skills: "/skills",
  settings: "/settings",
};

/** 路由路径 → ViewKey（Sidebar 高亮用；未匹配回退 chat） */
export function pathToView(pathname: string): ViewKey {
  if (pathname.startsWith("/skills")) return "skills";
  if (pathname.startsWith("/settings")) return "settings";
  return "chat";
}
