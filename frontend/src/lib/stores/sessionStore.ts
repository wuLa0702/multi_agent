/**
 * sessionStore — 会话列表（方案-前端设计-v1 §2：SessionList 数据源）。
 *
 * 职责边界：只管列表数据（load/rename/remove/create）。
 * 会话切换（select → loadHistory）由页面层编排（chatStore 与 sessionStore 解耦）。
 */

import { create } from "zustand";
import { api } from "@/lib/api/client";
import type { Session } from "@/lib/api/types";

interface SessionState {
  sessions: Session[];
  loaded: boolean;
  loadList(): Promise<void>;
  createSession(): Promise<Session>;
  rename(id: string, title: string): Promise<void>;
  togglePin(id: string, pinned: boolean): Promise<void>;
  remove(id: string): Promise<void>;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  loaded: false,

  async loadList() {
    const res = await api.listSessions();
    set({ sessions: res.items, loaded: true });
  },

  async createSession() {
    const session = await api.createSession();
    set((s) => ({ sessions: [session, ...s.sessions] }));
    return session;
  },

  async rename(id: string, title: string) {
    const updated = await api.updateSession(id, { title });
    set((s) => ({
      sessions: s.sessions.map((it) => (it.id === id ? updated : it)),
    }));
  },

  /** 置顶/取消置顶（2026-08-04 P0：后端 is_pinned + 本地兜底排序） */
  async togglePin(id: string, pinned: boolean) {
    const updated = await api.updateSession(id, { is_pinned: pinned });
    set((s) => ({
      sessions: s.sessions
        .map((it) => (it.id === id ? updated : it))
        .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned) || b.updated_at.localeCompare(a.updated_at)),
    }));
  },

  async remove(id: string) {
    await api.deleteSession(id);
    set((s) => ({ sessions: s.sessions.filter((it) => it.id !== id) }));
  },
}));
