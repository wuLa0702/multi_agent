/**
 * 一级导航视图定义（方案 §4.1：对话 / 能力市场 / 设置）。
 * 单用户场景：预留记忆、监控、帮助。
 */

export type ViewKey = "chat" | "skills" | "settings";

export const VIEWS: { key: ViewKey; label: string }[] = [
  { key: "chat", label: "对话" },
  { key: "skills", label: "能力市场" },
  { key: "settings", label: "设置" },
];
