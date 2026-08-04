/**
 * 能力市场页（方案 §5.2）— 二级栏分类导航 + 主区卡片网格（3 列）。
 * 分类：全部 / MCP Server / SKILL.md / 已安装（"全部"合并两类第一页）。
 * 顶部：搜索 + 仅看已安装开关；卡片含图标/名称/类型标签/简介/安装状态/升级。
 */

import { useEffect, useMemo, useState } from "react";
import { Store, Search, LayoutGrid, Plug, FileText, PackageCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSkillStore } from "@/lib/stores/skillStore";
import SkillCard from "@/components/skills/SkillCard";
import InstalledSkillRow from "@/components/skills/InstalledSkillRow";
import EmptyState from "@/components/shared/EmptyState";
import PageHeader from "@/components/common/PageHeader";
import SearchInput from "@/components/common/SearchInput";
import { showToast } from "@/components/shared/Toast";
import { api } from "@/lib/api/client";
import type { SkillMarketItem } from "@/lib/api/types";

type CategoryKey = "all" | "mcp_server" | "skill_md" | "installed";

const CATEGORIES: { key: CategoryKey; label: string; icon: typeof Plug; desc: string }[] = [
  { key: "all", label: "全部", icon: LayoutGrid, desc: "所有能力" },
  { key: "mcp_server", label: "MCP Server", icon: Plug, desc: "远程服务接入" },
  { key: "skill_md", label: "SKILL.md", icon: FileText, desc: "本地技能包" },
  { key: "installed", label: "已安装", icon: PackageCheck, desc: "管理已装能力" },
];

export default function SkillsPage() {
  const [category, setCategory] = useState<CategoryKey>("all");
  const [query, setQuery] = useState("");
  const [onlyInstalled, setOnlyInstalled] = useState(false);

  // 市场数据（skillStore 管理 mcp_server/skill_md 单类；"全部"由本页合并）
  const { marketItems, marketLoading, marketError, marketHasMore, installing, installed } =
    useSkillStore();
  const searchMarket = useSkillStore((s) => s.searchMarket);
  const loadMoreMarket = useSkillStore((s) => s.loadMoreMarket);
  const installSkill = useSkillStore((s) => s.installSkill);
  const toggleSkill = useSkillStore((s) => s.toggleSkill);
  const uninstallSkill = useSkillStore((s) => s.uninstallSkill);
  const loadInstalled = useSkillStore((s) => s.loadInstalled);

  // "全部"分类：本地合并两类第一页
  const [allItems, setAllItems] = useState<SkillMarketItem[]>([]);
  const [allLoading, setAllLoading] = useState(false);

  useEffect(() => {
    void loadInstalled().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 分类切换 → 拉数据
  useEffect(() => {
    if (category === "all") {
      setAllLoading(true);
      void Promise.all([
        api.listMarketSkills({ source: "smithery", query, page: 1, page_size: 20, skill_type: "mcp_server" }),
        api.listMarketSkills({ source: "smithery", query, page: 1, page_size: 20, skill_type: "skill_md" }),
      ])
        .then(([a, b]) => setAllItems([...a.items, ...b.items]))
        .catch(() => setAllItems([]))
        .finally(() => setAllLoading(false));
    } else if (category !== "installed") {
      void searchMarket("smithery", category, query).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  // 搜索触发（防抖简化：Enter 或按钮）
  const doSearch = () => {
    if (category === "all") {
      setAllLoading(true);
      void Promise.all([
        api.listMarketSkills({ source: "smithery", query, page: 1, page_size: 20, skill_type: "mcp_server" }),
        api.listMarketSkills({ source: "smithery", query, page: 1, page_size: 20, skill_type: "skill_md" }),
      ])
        .then(([a, b]) => setAllItems([...a.items, ...b.items]))
        .catch(() => setAllItems([]))
        .finally(() => setAllLoading(false));
    } else if (category !== "installed") {
      void searchMarket("smithery", category, query).catch(() => undefined);
    }
  };

  const installedUrls = useMemo(() => new Set(installed.map((i) => i.source_url)), [installed]);

  // 列表数据（按分类/搜索/仅看已安装过滤）
  const marketList = category === "all" ? allItems : marketItems;
  const loading = category === "all" ? allLoading : marketLoading;
  const filteredMarket = onlyInstalled ? marketList.filter((i) => installedUrls.has(i.source_url)) : marketList;

  // 已安装筛选
  const installedFiltered = query
    ? installed.filter((i) => i.name.toLowerCase().includes(query.toLowerCase()))
    : installed;

  const currentCat = CATEGORIES.find((c) => c.key === category)!;

  return (
    <div className="flex min-w-0 flex-1">
      {/* 二级栏：分类导航（v3 §5.2：删「已安装」勾选，仅保留主区开关） */}
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-border bg-card">
        <PageHeader title="能力市场" icon={<Store className="size-4" />} />
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => setCategory(c.key)}
              className={cn(
                "nav-item press relative flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                category === c.key ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
              )}
            >
              {category === c.key && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary" />
              )}
              <c.icon className={cn("size-4", category === c.key ? "text-primary" : "text-muted-foreground")} />
              <span className="flex-1">
                <span className="block text-xs font-medium">{c.label}</span>
                <span className="block text-[10px] text-muted-foreground">{c.desc}</span>
              </span>
              {c.key === "installed" && installed.length > 0 && (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                  {installed.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 顶部：标题栏 56px + 搜索筛选栏（v2 §4.2-1 独立一行） */}
        <PageHeader
          title={currentCat.label}
          right={
            category !== "installed" && (
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={onlyInstalled}
                  onChange={(e) => setOnlyInstalled(e.target.checked)}
                  className="size-3.5 accent-primary"
                />
                仅看已安装
              </label>
            )
          }
        >
          <div className="flex items-center gap-2 px-4 pb-2.5">
            <div className="w-1/2">
              <SearchInput
                value={query}
                onChange={setQuery}
                placeholder="搜索市场 Skill…"
                onEnter={doSearch}
              />
            </div>
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={doSearch}>
              搜索
            </Button>
          </div>
        </PageHeader>

        {/* 内容区：卡片网格 3 列（方案 §5.2.2-2）或已安装列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {category === "installed" ? (
            <div className="mx-auto max-w-[760px] space-y-2">
              {installedFiltered.length === 0 && (
                <EmptyState icon={PackageCheck} title="暂无已安装 Skill" desc="去「全部」分类浏览安装" />
              )}
              {installedFiltered.map((skill) => (
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
          ) : (
            <>
              {loading && filteredMarket.length === 0 && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="skeleton-pulse h-28 rounded-xl border border-border bg-muted" />
                  ))}
                </div>
              )}
              {!loading && !marketError && filteredMarket.length === 0 && (
                <EmptyState icon={Search} title="没有找到 Skill" desc="换个关键词或分类试试" />
              )}
              {marketError && category !== "all" && (
                <div className="py-8 text-center">
                  <p className="text-xs text-destructive">{marketError}</p>
                  <Button size="sm" variant="outline" className="mt-2 h-7 text-xs" onClick={doSearch}>
                    重试
                  </Button>
                </div>
              )}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {filteredMarket.map((item) => (
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
              </div>
              {category !== "all" && marketHasMore && !onlyInstalled && (
                <div className="mt-4 text-center">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => void loadMoreMarket().catch(() => undefined)}
                    disabled={marketLoading}
                  >
                    {marketLoading ? "加载中…" : "加载更多"}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
