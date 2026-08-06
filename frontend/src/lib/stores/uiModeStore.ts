/**
 * uiModeStore — UI 模式状态（v5.0 §3.3/§3.4）。
 * 模式：chat（对话）/ subagent（子代理）/ todo（任务规划）/ sandbox（沙箱，预留）。
 * 规则：自动检测单向升级（低→高）；手动切换优先级最高；不自动降级；会话记忆（localStorage）。
 */

import { create } from "zustand";

export type UiMode = "chat" | "subagent" | "todo" | "sandbox";

/** 模式优先级（自动检测单向升级用；沙箱最高） */
const MODE_RANK: Record<UiMode, number> = { chat: 0, subagent: 1, todo: 2, sandbox: 3 };

const UI_MODE_KEY = "multi-agent.uiMode";

interface UiModeState {
  mode: UiMode;
  /** 手动覆盖标记（自动检测不覆盖手动选择，v5.0 §3.3） */
  manualOverride: boolean;
  setMode: (mode: UiMode, manual?: boolean) => void;
  /** 自动检测升级：仅当目标优先级更高且非手动覆盖时生效（v5.0 §3.2 单向升级） */
  autoUpgrade: (target: UiMode) => void;
}

function readSaved(): UiMode {
  const saved = localStorage.getItem(UI_MODE_KEY);
  return saved === "subagent" || saved === "todo" || saved === "sandbox" ? saved : "chat";
}

export const useUiModeStore = create<UiModeState>((set, get) => ({
  mode: readSaved(),
  manualOverride: false,

  setMode: (mode, manual = false) => {
    localStorage.setItem(UI_MODE_KEY, mode);
    set({ mode, manualOverride: manual });
  },

  autoUpgrade: (target) => {
    const { mode, manualOverride } = get();
    if (manualOverride) return; // 手动选择优先，自动检测不覆盖
    if (MODE_RANK[target] > MODE_RANK[mode]) {
      localStorage.setItem(UI_MODE_KEY, target);
      set({ mode: target });
    }
  },
}));
