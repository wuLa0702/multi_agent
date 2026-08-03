import { type LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  desc?: string;
  action?: { label: string; onClick: () => void };
}

/**
 * 视觉化空状态组件 — SVG 插画 + 标题 + 描述 + 可选操作按钮
 */
export default function EmptyState({ icon: Icon, title, desc, action }: EmptyStateProps) {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center max-w-sm px-6">
        {/* Decorative illustration area */}
        <div className="relative mx-auto mb-6 w-24 h-24">
          <div className="absolute inset-0 rounded-full bg-gradient-to-br from-primary/5 via-primary/10 to-transparent" />
          <div className="absolute inset-2 rounded-full bg-gradient-to-br from-primary/8 to-transparent" />
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center shadow-sm ring-1 ring-primary/5">
              <Icon className="h-7 w-7 text-muted-foreground/60" strokeWidth={1.2} />
            </div>
          </div>
        </div>
        <h3 className="text-base font-semibold text-foreground mb-1.5">{title}</h3>
        {desc && <p className="text-sm text-muted-foreground/70 leading-relaxed">{desc}</p>}
        {action && (
          <button
            className="mt-5 px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer shadow-sm"
            onClick={action.onClick}
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
