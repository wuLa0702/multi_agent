/**
 * SkillMarketPanel — Skill 市场主面板（ChatPage 左侧栏 Skills 标签页）。
 *
 * 两个子视图 Tab（store.activeTab）：market（浏览/搜索/安装）+ installed（开关/卸载）。
 * 挂载时自动加载已安装列表 + 市场热门；安装/切换/卸载走 skillStore（后端已触发热加载）。
 */

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, RefreshCw } from "lucide-react";
import { useSkillStore } from "@/lib/stores/skillStore";
import SkillCard from "@/components/skills/SkillCard";
import InstalledSkillRow from "@/components/skills/InstalledSkillRow";
import EmptyState from "@/components/shared/EmptyState";
import { showToast } from "@/components/shared/Toast";

export default function SkillMarketPanel() {
  const activeTab = useSkillStore((s) => s.activeTab);
  const loadInstalled = useSkillStore((s) => s.loadInstalled);

  useEffect(() => {
    void loadInstalled().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return activeTab === "market" ? <MarketView /> : <InstalledView />;
}

// ── 市场视图 ──

function MarketView() {
  const {
    marketItems,
    marketLoading,
    marketError,
    marketHasMore,
    marketType,
    installing,
    installed,
  } = useSkillStore();
  const setTab = useSkillStore((s) => s.setTab);
  const searchMarket = useSkillStore((s) => s.searchMarket);
  const loadMoreMarket = useSkillStore((s) => s.loadMoreMarket);
  const installSkill = useSkillStore((s) => s.installSkill);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void searchMarket("smithery", marketType, "").catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const installedUrls = new Set(installed.map((i) => i.source_url));

  const doSearch = (type: "mcp_server" | "skill_md") =>
    void searchMarket("smithery", type, query).catch(() => undefined);

  return (
    <div className="flex h-full flex-col">
      <div className="p-2 space-y-2 border-b border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center gap-1.5">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") doSearch(marketType);
            }}
            placeholder="搜索市场 Skill…"
            className="h-7 text-xs"
          />
          <Button
            size="icon"
            variant="outline"
            className="h-7 w-7 shrink-0"
            onClick={() => doSearch(marketType)}
            title="搜索"
          >
            <Search className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant={marketType === "mcp_server" ? "default" : "outline"}
            className="h-6 text-xs px-2"
            onClick={() => doSearch("mcp_server")}
          >
            MCP Server
          </Button>
          <Button
            size="sm"
            variant={marketType === "skill_md" ? "default" : "outline"}
            className="h-6 text-xs px-2"
            onClick={() => doSearch("skill_md")}
          >
            SKILL.md
          </Button>
          <button
            onClick={() => setTab("installed")}
            className="ml-auto text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            已安装 {installed.length} →
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {marketLoading && marketItems.length === 0 && (
          <p className="text-center text-xs text-neutral-400 py-8">加载中…</p>
        )}
        {marketError && (
          <div className="text-center py-8 space-y-2">
            <p className="text-xs text-red-500">{marketError}</p>
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-xs"
              onClick={() => doSearch(marketType)}
            >
              <RefreshCw className="h-3 w-3 mr-1" /> 重试
            </Button>
          </div>
        )}
        {!marketLoading && !marketError && marketItems.length === 0 && (
          <EmptyState icon={Search} title="没有 Skill" desc="换个关键词或重试" />
        )}
        {marketItems.map((item) => (
          <SkillCard
            key={item.source_url}
            item={item}
            installing={installing.has(item.source_url)}
            installed={installedUrls.has(item.source_url)}
            onInstall={async (it, force) => {
              await installSkill(it, force);
              showToast(force ? `已升级 ${it.name}` : `已安装 ${it.name}`, "success");
            }}
          />
        ))}
        {marketHasMore && (
          <div className="text-center py-2">
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs"
              onClick={() => void loadMoreMarket().catch(() => undefined)}
              disabled={marketLoading}
            >
              {marketLoading ? "加载中…" : "加载更多"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 已安装视图 ──

function InstalledView() {
  const { installed, installedLoaded } = useSkillStore();
  const setTab = useSkillStore((s) => s.setTab);
  const toggleSkill = useSkillStore((s) => s.toggleSkill);
  const uninstallSkill = useSkillStore((s) => s.uninstallSkill);
  const [query, setQuery] = useState("");

  const filtered = query ? installed.filter((i) => i.name.includes(query)) : installed;

  return (
    <div className="flex h-full flex-col">
      <div className="p-2 border-b border-neutral-200 dark:border-neutral-800 space-y-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="筛选已安装…"
          className="h-7 text-xs"
        />
        <button
          onClick={() => setTab("market")}
          className="text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        >
          ← 去市场浏览
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {!installedLoaded && <p className="text-center text-xs text-neutral-400 py-8">加载中…</p>}
        {installedLoaded && filtered.length === 0 && (
          <EmptyState icon={Search} title="暂无已安装 Skill" desc="去市场 Tab 浏览安装" />
        )}
        {filtered.map((skill) => (
          <InstalledSkillRow
            key={skill.id}
            skill={skill}
            onToggle={async (id, active) => {
              await toggleSkill(id, active);
              showToast(active ? "已启用" : "已停用", "success");
            }}
            onUninstall={async (id) => {
              await uninstallSkill(id);
              showToast("已卸载", "success");
            }}
          />
        ))}
      </div>
    </div>
  );
}
