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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/stores/chatStore";
import { useSkillStore } from "@/lib/stores/skillStore";
import InstalledSkillRow from "@/components/skills/InstalledSkillRow";
import { showToast } from "@/components/shared/Toast";
import { showConfirm } from "@/components/ui/confirm-dialog";
import type { ProviderInfo } from "@/lib/api/types";

type SettingKey = "account" | "mcp" | "skills" | "system";

const SETTING_MENU: { key: SettingKey; label: string; icon: typeof KeyRound; desc: string }[] = [
  { key: "account", label: "账户与密钥", icon: KeyRound, desc: "模型厂商 API Key 配置" },
  { key: "mcp", label: "MCP 管理", icon: Plug, desc: "外部 MCP Server 连接" },
  { key: "skills", label: "Skill 管理", icon: PackageCheck, desc: "已安装技能包" },
  { key: "system", label: "系统配置", icon: Settings2, desc: "运行行为与偏好" },
];

// ── mock 数据（后端未实现的接口，标注 ⚠️ MOCK）──

interface MockMcpRow {
  id: string;
  name: string;
  type: string;
  endpoint: string;
  active: boolean;
}

/** ⚠️ MOCK：MCP 管理行（后端无管理 API，演示用） */
const MOCK_MCP_ROWS: MockMcpRow[] = [
  { id: "gw", name: "Smithery 网关", type: "streamable_http", endpoint: "api.smithery.ai/connect/…/mcp", active: true },
  { id: "bocha", name: "博查搜索", type: "http", endpoint: "api.bocha.cn/v1", active: true },
  { id: "sandbox", name: "OpenSandbox", type: "http", endpoint: "localhost:8080", active: true },
];

interface MockSwitch {
  key: string;
  label: string;
  desc: string;
  value: boolean;
}

/** ⚠️ MOCK：系统配置开关（后端无接口，演示用） */
const MOCK_SYSTEM_SWITCHES: MockSwitch[] = [
  { key: "log_report", label: "前端日志上报", desc: "将前端错误批量上报到后端（当前 console-only）", value: false },
  { key: "auto_update", label: "Skill 自动更新", desc: "市场技能有新版本时自动升级", value: false },
  { key: "stream_accel", label: "流式渲染加速", desc: "逐字渲染 vs 分块渲染（大模型长文更流畅）", value: true },
];

export default function SettingsPage() {
  const [menu, setMenu] = useState<SettingKey>("account");
  const providers = useChatStore((s) => s.providers);
  const loadProviders = useChatStore((s) => s.loadProviders);
  const { installed, installedLoaded } = useSkillStore();
  const loadInstalled = useSkillStore((s) => s.loadInstalled);
  const toggleSkill = useSkillStore((s) => s.toggleSkill);
  const uninstallSkill = useSkillStore((s) => s.uninstallSkill);

  // mock 开关状态（本地 state）
  const [switches, setSwitches] = useState<Record<string, boolean>>(
    Object.fromEntries(MOCK_SYSTEM_SWITCHES.map((s) => [s.key, s.value])),
  );
  const [mockMcp, setMockMcp] = useState<MockMcpRow[]>(MOCK_MCP_ROWS);

  useEffect(() => {
    void loadProviders();
    void loadInstalled().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          {menu === "mcp" && (
            <McpSection rows={mockMcp} onToggle={(id) => setMockMcp((r) => r.map((x) => (x.id === id ? { ...x, active: !x.active } : x)))} />
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
              {MOCK_SYSTEM_SWITCHES.map((s) => (
                <SwitchCard
                  key={s.key}
                  label={s.label}
                  desc={s.desc}
                  checked={switches[s.key]}
                  onChange={(v) => {
                    setSwitches((prev) => ({ ...prev, [s.key]: v }));
                    showToast(`${s.label}：${v ? "已开启" : "已关闭"}`, "success");
                  }}
                  mock
                />
              ))}
            </div>
          )}
        </div>
      </main>
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
    </div>
  );
}

// ── MCP 管理（⚠️ MOCK 数据）──

function McpSection({
  rows,
  onToggle,
}: {
  rows: MockMcpRow[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-warning">⚠️ MOCK：后端无 MCP 管理接口，以下为演示数据</p>
      {rows.map((r) => (
        <div key={r.id} className="card-hover flex items-center gap-3 rounded-xl border border-border bg-card p-3.5 shadow-xs">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
            {r.type === "http" ? <Globe className="size-4" /> : <Server className="size-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium">
              {r.name}
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{r.type}</span>
            </div>
            <div className="truncate text-xs text-muted-foreground">{r.endpoint}</div>
          </div>
          <button
            type="button"
            onClick={() => onToggle(r.id)}
            className={cn(
              "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200",
              r.active ? "bg-primary" : "bg-muted-foreground/40",
            )}
            title={r.active ? "点击停用" : "点击启用"}
            aria-label={`${r.active ? "停用" : "启用"} ${r.name}`}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200",
                r.active ? "translate-x-[18px]" : "translate-x-[3px]",
              )}
            />
          </button>
          <button
            type="button"
            onClick={() => void showConfirm(`删除 MCP 连接「${r.name}」？（mock）`).then((ok) => ok && showToast("已删除（mock）", "success"))}
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
