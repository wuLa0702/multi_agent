/**
 * SearchInput — 统一搜索框（圆角、放大镜图标、h-8）。
 * 会话列表 / 能力市场 / 设置页复用。
 */

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  onEnter?: () => void;
}

export default function SearchInput({ value, onChange, placeholder = "搜索…", onEnter }: Props) {
  return (
    <div className="relative">
      <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        placeholder={placeholder}
        className="h-8 pl-7 text-xs"
      />
    </div>
  );
}
