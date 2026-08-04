/**
 * usePinnedSessions — 会话置顶持久化（v3 §4.1）。
 * ⚠️ MOCK：后端无 isPinned 接口，用 localStorage 持久化（刷新不丢失）。
 */

import { useCallback, useState } from "react";

const STORAGE_KEY = "multi-agent.pinned-sessions";

function load(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function save(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // localStorage 不可用则仅内存态
  }
}

export function usePinnedSessions() {
  const [pinned, setPinned] = useState<string[]>(load);

  const isPinned = useCallback((id: string) => pinned.includes(id), [pinned]);

  const togglePinned = useCallback((id: string) => {
    setPinned((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [id, ...prev];
      save(next);
      return next;
    });
  }, []);

  return { pinned, isPinned, togglePinned };
}
