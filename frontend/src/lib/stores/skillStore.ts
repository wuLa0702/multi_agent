/**
 * skillStore — Skill Market 状态（市场浏览 + 已安装管理）。
 *
 * 职责边界：
 * - 市场浏览：searchMarket / loadMoreMarket（Smithery 代理，带分页）
 * - 已安装：loadInstalled / installSkill / toggleSkill / uninstallSkill
 * - 安装后自动刷新已安装列表（后端已触发热加载，前端只需重新拉取）
 */

import { create } from "zustand";
import { api } from "@/lib/api/client";
import type { InstalledSkill, SkillMarketItem } from "@/lib/api/types";

interface SkillState {
  // 视图：market（市场浏览）/ installed（已安装管理）
  activeTab: "market" | "installed";

  // 市场浏览
  marketItems: SkillMarketItem[];
  marketLoading: boolean;
  marketSource: string;
  marketType: "mcp_server" | "skill_md";
  marketQuery: string;
  marketPage: number;
  marketHasMore: boolean;
  marketError: string | null;

  // 已安装
  installed: InstalledSkill[];
  installedLoaded: boolean;
  installing: Set<string>; // 安装中的 source_url（按钮 spinner）

  // 动作
  setTab(tab: "market" | "installed"): void;
  searchMarket(source: string, type: "mcp_server" | "skill_md", query: string): Promise<void>;
  loadMoreMarket(): Promise<void>;
  loadInstalled(): Promise<void>;
  installSkill(item: SkillMarketItem, force?: boolean): Promise<void>;
  toggleSkill(id: number, active: boolean): Promise<void>;
  uninstallSkill(id: number): Promise<void>;
}

export const useSkillStore = create<SkillState>((set, get) => ({
  activeTab: "market",

  marketItems: [],
  marketLoading: false,
  marketSource: "smithery",
  marketType: "mcp_server",
  marketQuery: "",
  marketPage: 1,
  marketHasMore: false,
  marketError: null,

  installed: [],
  installedLoaded: false,
  installing: new Set(),

  setTab(tab) {
    set({ activeTab: tab });
  },

  async searchMarket(source, type, query) {
    set({ marketLoading: true, marketSource: source, marketType: type, marketQuery: query, marketError: null });
    try {
      const res = await api.listMarketSkills({ source, query, page: 1, page_size: 20, skill_type: type });
      set({ marketItems: res.items, marketPage: 1, marketHasMore: res.has_more, marketLoading: false });
    } catch (e) {
      set({ marketItems: [], marketLoading: false, marketError: e instanceof Error ? e.message : "市场加载失败" });
    }
  },

  async loadMoreMarket() {
    const { marketSource, marketType, marketQuery, marketPage, marketLoading, marketHasMore } = get();
    if (marketLoading || !marketHasMore) return;
    set({ marketLoading: true });
    try {
      const res = await api.listMarketSkills({
        source: marketSource,
        query: marketQuery,
        page: marketPage + 1,
        page_size: 20,
        skill_type: marketType,
      });
      set((s) => ({
        marketItems: [...s.marketItems, ...res.items],
        marketPage: marketPage + 1,
        marketHasMore: res.has_more,
        marketLoading: false,
      }));
    } catch (e) {
      set({ marketLoading: false, marketError: e instanceof Error ? e.message : "加载更多失败" });
    }
  },

  async loadInstalled() {
    const res = await api.listInstalledSkills();
    set({ installed: res.items, installedLoaded: true });
  },

  async installSkill(item, force = false) {
    const key = item.source_url;
    if (get().installing.has(key)) return;
    set((s) => ({ installing: new Set(s.installing).add(key) }));
    try {
      const installed = await api.installSkill({
        source: item.source,
        source_url: item.source_url,
        name: item.name,
        skill_type: item.skill_type,
        transport: item.transport,
        url: item.url,
        command: item.command,
        args: item.args,
        git_url: item.git_url,
        force,
      });
      set((s) => ({
        installed: [installed, ...s.installed.filter((it) => it.source_url !== item.source_url)],
      }));
    } finally {
      set((s) => {
        const next = new Set(s.installing);
        next.delete(key);
        return { installing: next };
      });
    }
  },

  async toggleSkill(id, active) {
    const updated = await api.updateSkill(id, { is_active: active });
    set((s) => ({
      installed: s.installed.map((sk) => (sk.id === id ? { ...sk, is_active: updated.is_active } : sk)),
    }));
  },

  async uninstallSkill(id) {
    await api.deleteSkill(id);
    set((s) => ({ installed: s.installed.filter((sk) => sk.id !== id) }));
  },
}));
