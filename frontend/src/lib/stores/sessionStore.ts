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
    const updated = await api.updateSessionTitle(id, title);
    set((s) => ({
      sessions: s.sessions.map((it) => (it.id === id ? updated : it)),
    }));
  },

  async remove(id: string) {
    await api.deleteSession(id);
    set((s) => ({ sessions: s.sessions.filter((it) => it.id !== id) }));
  },
}));
