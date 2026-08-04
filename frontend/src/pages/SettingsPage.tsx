/**
 * 设置页（方案 §5.3）— 二级栏设置菜单 + 主区配置卡片列表。
 * 数据：账户与密钥（GET /v1/providers 真实）、MCP 管理（mock）、
 * Skill 管理（GET /v1/skills/installed 真实）、系统配置（mock 开关）。
 * 后端未有的功能用 mock 数据（标注 ⚠️ MOCK）。
 */

import { useEffect, useState } from "react";
import {
  KeyRound,
  Plug,
  PackageCheck,
  Settings2,
  Check,
  Pencil,
  Trash2,
  Server,
  Globe,
  Palette,
  Plus,
  Moon,
  Sun,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import { useChatStore } from "@/lib/stores/chatStore";
import { useSkillStore } from "@/lib/stores/skillStore";
import { useTheme } from "@/hooks/useTheme";
import InstalledSkillRow from "@/components/skills/InstalledSkillRow";
import { showToast } from "@/components/shared/Toast";
import { showConfirm } from "@/components/ui/confirm-dialog";
import type { McpServerInfo, ProviderInfo } from "@/lib/api/types";

type SettingKey = "account" | "mcp" | "skills" | "system" | "appearance";

const SETTING_MENU: { key: SettingKey; label: string; icon: typeof KeyRound; desc: string }[] = [
  { key: "account", label: "账户与密钥", icon: KeyRound, desc: "模型厂商 API Key 配置" },
  { key: "mcp", label: "MCP 管理", icon: Plug, desc: "外部 MCP Server 连接" },
  { key: "skills", label: "Skill 管理", icon: PackageCheck, desc: "已安装技能包" },
  { key: "system", label: "系统配置", icon: Settings2, desc: "运行行为与偏好" },
  { key: "appearance", label: "外观主题", icon: Palette, desc: "亮色 / 暗色 / 跟随系统" },
];

// ── 系统配置开关定义（真实持久化，2026-08-04 P1 去 mock）──

interface SwitchDef {
  key: string;
  label: string;
  desc: string;
  value: boolean; // 默认值（后端无配置时）
}

const SYSTEM_SWITCHES: SwitchDef[] = [
  { key: "log_report", label: "前端日志上报", desc: "将前端错误批量上报到后端 logs/frontend.log", value: false },
  { key: "auto_update", label: "Skill 自动更新", desc: "市场技能有新版本时自动升级", value: false },
  { key: "stream_accel", label: "流式渲染加速", desc: "逐字渲染 vs 分块渲染（大模型长文更流畅）", value: true },
];

export default function SettingsPage() {
  const [menu, setMenu] = useState<SettingKey>("account");
  const providers = useChatStore((s) => s.providers);
  const loadProviders = useChatStore((s) => s.loadProviders);
  const { theme, setTheme } = useTheme();
  const { installed, installedLoaded } = useSkillStore();
  const loadInstalled = useSkillStore((s) => s.loadInstalled);
  const toggleSkill = useSkillStore((s) => s.toggleSkill);
  const uninstallSkill = useSkillStore((s) => s.uninstallSkill);

  // 真实数据（2026-08-04 P1 去 mock）：MCP 连接 + 系统配置
  const [mcpServers, setMcpServers] = useState<McpServerInfo[]>([]);
  const [mcpLoading, setMcpLoading] = useState(true);
  const [switches, setSwitches] = useState<Record<string, boolean>>({});
  const [settingsLoaded, setSettingsLoaded] = useState(false);

  useEffect(() => {
    void loadProviders();
    void loadInstalled().catch(() => undefined);
    // MCP 连接列表（真实）
    void api
      .listMcpServers()
      .then((res) => setMcpServers(res.items))
      .catch(() => setMcpServers([]))
      .finally(() => setMcpLoading(false));
    // 系统配置（真实，缺省用默认值）
    void api
      .getSettings()
      .then((res) => {
        const parsed: Record<string, boolean> = {};
        for (const s of SYSTEM_SWITCHES) {
          const raw = res.settings[s.key];
          parsed[s.key] = raw === undefined ? s.value : raw === "true";
        }
        setSwitches(parsed);
        setSettingsLoaded(true);
      })
      .catch(() => {
        setSwitches(Object.fromEntries(SYSTEM_SWITCHES.map((s) => [s.key, s.value])));
        setSettingsLoaded(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 开关变更 → 后端持久化 */
  const handleSwitchChange = (key: string, value: boolean) => {
    setSwitches((prev) => ({ ...prev, [key]: value }));
    void api.putSettings({ [key]: String(value) }).catch(() => showToast("配置保存失败", "error"));
    showToast(value ? "已开启" : "已关闭", "success");
  };

  const current = SETTING_MENU.find((m) => m.key === menu)!;

  return (
    <div className="flex min-w-0 flex-1">
      {/* 二级栏：设置菜单（方案 §5.3.2-1） */}
      <aside className="w-[280px] shrink-0 border-r border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Settings2 className="size-4 text-primary" />
          <span className="text-sm font-semibold">设置</span>
        </div>
        <div className="space-y-0.5 p-2">
          {SETTING_MENU.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setMenu(m.key)}
              className={cn(
                "nav-item press relative flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors",
                menu === m.key ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
              )}
            >
              {menu === m.key && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary" />
              )}
              <m.icon className={cn("size-4", menu === m.key ? "text-primary" : "text-muted-foreground")} />
              <span className="flex-1">
                <span className="block text-xs font-medium">{m.label}</span>
                <span className="block text-[10px] text-muted-foreground">{m.desc}</span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[860px] p-5">
          <header className="mb-4">
            <h1 className="text-base font-semibold">{current.label}</h1>
            <p className="text-xs text-muted-foreground">{current.desc}</p>
          </header>

          {menu === "account" && <AccountSection providers={providers} />}
          {menu === "appearance" && (
            <div className="space-y-2">
              {(
                [
                  { key: "light", label: "亮色", desc: "明亮主题，适合白天", icon: Sun },
                  { key: "dark", label: "暗色", desc: "深色主题，护眼省电", icon: Moon },
                  { key: "system", label: "跟随系统", desc: "随操作系统自动切换", icon: Settings2 },
                ] as const
              ).map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => {
                    setTheme(t.key);
                    showToast(`已切换为${t.label}主题`, "success");
                  }}
                  className={cn(
                    "card-hover press flex w-full items-center gap-3 rounded-xl border p-4 text-left shadow-xs",
                    theme === t.key ? "border-primary/50 bg-accent/40" : "border-border bg-card",
                  )}
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-primary">
                    <t.icon className="size-5" />
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-medium">{t.label}</div>
                    <div className="text-xs text-muted-foreground">{t.desc}</div>
                  </div>
                  {theme === t.key && <Check className="size-4 text-success" />}
                </button>
              ))}

              {/* 字体大小三档（v3 §6.1：CSS 变量 --font-size-base + 实时预览） */}
              <FontSizeSection />
            </div>
          )}
          {menu === "mcp" && (
            <McpSection
              rows={mcpServers}
              loading={mcpLoading}
              onToggle={async (id, active) => {
                await api.updateMcpServer(id, { is_active: active }).catch(() => showToast("操作失败", "error"));
                setMcpServers((prev) => prev.map((x) => (x.id === id ? { ...x, is_active: active } : x)));
                showToast(active ? "已启用" : "已停用", "success");
              }}
              onDelete={async (id) => {
                const ok = await showConfirm("删除该 MCP 连接？（关联 Skill 记录一并删除）", {
                  title: "删除连接",
                  confirmLabel: "删除",
                  variant: "destructive",
                });
                if (!ok) return;
                await api.deleteMcpServer(id).catch(() => showToast("删除失败", "error"));
                setMcpServers((prev) => prev.filter((x) => x.id !== id));
                showToast("已删除", "success");
              }}
            />
          )}
          {menu === "skills" && (
            <div className="space-y-2">
              {installedLoaded && installed.length === 0 && (
                <p className="py-8 text-center text-xs text-muted-foreground">暂无已安装 Skill，去能力市场安装</p>
              )}
              {installed.map((skill) => (
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
          )}
          {menu === "system" && (
            <div className="space-y-2">
              {!settingsLoaded && (
                <p className="py-8 text-center text-xs text-muted-foreground">加载配置中…</p>
              )}
              {settingsLoaded &&
                SYSTEM_SWITCHES.map((s) => (
                  <SwitchCard
                    key={s.key}
                    label={s.label}
                    desc={s.desc}
                    checked={switches[s.key] ?? s.value}
                    onChange={(v) => handleSwitchChange(s.key, v)}
                  />
                ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ── 字体大小（v3 §6.1：三档 + 实时预览，CSS 变量驱动全局生效）──

const FONT_SIZES = [
  { key: "small", label: "小", px: 13, desc: "大屏 / 内容密集" },
  { key: "medium", label: "中（默认）", px: 14, desc: "常规使用" },
  { key: "large", label: "大", px: 16, desc: "小屏 / 视力偏好" },
] as const;

function FontSizeSection() {
  const [current, setCurrent] = useState<number>(() => {
    const v = getComputedStyle(document.documentElement).getPropertyValue("--font-size-base").trim();
    const px = Number.parseFloat(v);
    return Number.isFinite(px) && px > 0 ? px : 14;
  });

  const apply = (px: number) => {
    document.documentElement.style.setProperty("--font-size-base", `${px}px`);
    setCurrent(px);
    showToast(`字体大小已切换（${px}px）`, "success");
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        字体大小
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">本地</span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {FONT_SIZES.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => apply(f.px)}
            className={cn(
              "press rounded-lg border p-2.5 text-center transition-colors",
              current === f.px ? "border-primary/50 bg-accent/40" : "border-border hover:bg-muted",
            )}
          >
            <div className="font-medium" style={{ fontSize: `${f.px}px` }}>
              示例
            </div>
            <div className="mt-1 text-[10px] text-muted-foreground">
              {f.label} · {f.px}px
            </div>
          </button>
        ))}
      </div>
      {/* 实时预览（v3 §6.1-3） */}
      <p className="mt-3 border-t border-border pt-2 text-muted-foreground" style={{ fontSize: `${current}px` }}>
        实时预览：这是当前字号效果，对话消息与会话列表同步变化。
      </p>
    </div>
  );
}

// ── 账户与密钥（真实数据 GET /v1/providers）──

function AccountSection({ providers }: { providers: ProviderInfo[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {providers.map((p) => (
        <div key={p.slug} className="card-hover flex items-start justify-between rounded-xl border border-border bg-card p-4 shadow-xs">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent font-semibold text-primary">
              {p.name.charAt(0)}
            </div>
            <div>
              <div className="flex items-center gap-2 text-sm font-medium">
                {p.name}
                {p.is_active && <Check className="size-3.5 text-success" />}
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {p.models.length} 个模型 · slug: {p.slug}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {p.models.slice(0, 4).map((m) => (
                  <span key={m.id} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {m.name}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => showToast("API Key 编辑弹窗（后端未实现，mock）", "info")}
            className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted"
            aria-label="编辑"
          >
            <Pencil className="size-3.5" />
          </button>
        </div>
      ))}

      {/* 添加新账户（v2 §5.2-3，mock） */}
      <button
        type="button"
        onClick={() => showToast("添加新账户（后端未实现，mock）", "info")}
        className="card-hover press flex h-20 items-center justify-center gap-2 rounded-xl border border-dashed border-border text-xs text-muted-foreground hover:border-primary/40 hover:text-primary"
      >
        <Plus className="size-4" /> 添加新账户
      </button>
    </div>
  );
}

// ── MCP 管理（真实数据 GET /v1/mcp-servers，2026-08-04 P1 去 mock）──

function McpSection({
  rows,
  loading,
  onToggle,
  onDelete,
}: {
  rows: McpServerInfo[];
  loading: boolean;
  onToggle: (id: number, active: boolean) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <div className="space-y-2">
      {loading && <p className="py-8 text-center text-xs text-muted-foreground">加载中…</p>}
      {!loading && rows.length === 0 && (
        <p className="py-8 text-center text-xs text-muted-foreground">
          暂无 MCP 连接，去能力市场安装 Skill 或手动配置
        </p>
      )}
      {rows.map((r) => (
        <div key={r.id} className="card-hover flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 shadow-xs">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
            {r.transport === "http" ? <Globe className="size-4" /> : <Server className="size-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium">
              {r.name}
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{r.transport}</span>
              {r.source !== "manual" && (
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{r.source}</span>
              )}
            </div>
            <div className="truncate text-xs text-muted-foreground">{r.url || "—"}</div>
          </div>
          <button
            type="button"
            onClick={() => onToggle(r.id, !r.is_active)}
            className={cn(
              "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200",
              r.is_active ? "bg-primary" : "bg-muted-foreground/40",
            )}
            title={r.is_active ? "点击停用" : "点击启用"}
            aria-label={`${r.is_active ? "停用" : "启用"} ${r.name}`}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200",
                r.is_active ? "translate-x-[18px]" : "translate-x-[3px]",
              )}
            />
          </button>
          <button
            type="button"
            onClick={() => onDelete(r.id)}
            className="press rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
            aria-label="删除"
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ── 通用开关卡片 ──

function SwitchCard({
  label,
  desc,
  checked,
  onChange,
  mock = false,
}: {
  label: string;
  desc: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  mock?: boolean;
}) {
  return (
    <div className="card-hover flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 shadow-xs">
      <div>
        <div className="flex items-center gap-2 text-sm font-medium">
          {label}
          {mock && <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">MOCK</span>}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">{desc}</div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200",
          checked ? "bg-primary" : "bg-muted-foreground/40",
        )}
        role="switch"
        aria-checked={checked}
        aria-label={label}
      >
        <span
          className={cn(
            "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200",
            checked ? "translate-x-[18px]" : "translate-x-[3px]",
          )}
        />
      </button>
    </div>
  );
}
