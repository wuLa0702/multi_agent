/**
 * Sidebar — 一级导航栏（64px 宽，纯图标，无滚动条）。
 *
 * 方案 §4.1.2：顶部功能导航（对话/市场，预留记忆/监控/帮助），
 * 底部工具区（主题切换 + 设置）。选中项左侧 3px 主题色竖条 + 浅底。
 *
 * v6 评审 P0-2 方案A：高亮读 useLocation() 匹配路由，跳转走 navigate()。
 */

import { MessageSquare, Store, Settings, Moon, Sun } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTheme } from "@/hooks/useTheme";
import { VIEW_PATHS, pathToView, type ViewKey } from "@/lib/navigation";

export default function Sidebar() {
  const { resolvedTheme, setTheme } = useTheme();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const activeView = pathToView(pathname);

  const cycleTheme = () => {
    // 三态循环：dark → light → system
    const next = resolvedTheme === "dark" ? "light" : "dark";
    setTheme(next);
  };

  const go = (view: ViewKey) => navigate(VIEW_PATHS[view]);

  return (
    <nav
      className="flex w-16 shrink-0 flex-col items-center border-r border-border bg-sidebar py-3"
      aria-label="一级导航"
    >
      {/* 顶部：功能导航 */}
      <div className="flex flex-col items-center gap-1.5">
        <NavIcon
          label="对话"
          active={activeView === "chat"}
          onClick={() => go("chat")}
        >
          <MessageSquare className="h-5 w-5" />
        </NavIcon>
        <NavIcon
          label="能力市场"
          active={activeView === "skills"}
          onClick={() => go("skills")}
        >
          <Store className="h-5 w-5" />
        </NavIcon>
      </div>

      {/* 弹性占位 */}
      <div className="flex-1" />

      {/* 底部：工具区 */}
      <div className="flex flex-col items-center gap-1.5">
        <NavIcon label={resolvedTheme === "dark" ? "切换亮色" : "切换暗色"} onClick={cycleTheme}>
          {resolvedTheme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </NavIcon>
        <NavIcon
          label="设置"
          active={activeView === "settings"}
          onClick={() => go("settings")}
        >
          <Settings className="h-5 w-5" />
        </NavIcon>
      </div>
    </nav>
  );
}

function NavIcon({
  label,
  active = false,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      data-slot="sidebar-menu-button"
      data-active={active || undefined}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={`nav-item press flex h-11 w-11 items-center justify-center rounded-lg transition-colors ${
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
      }`}
    >
      {children}
    </button>
  );
}
