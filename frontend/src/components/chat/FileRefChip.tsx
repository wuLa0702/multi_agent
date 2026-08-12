import type { FileRef } from "@/lib/api/types";

/** 文件引用渲染（F6，2026-08-12）：展示后端返回的相对路径（前端不拼接/不校验） */
function fileIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "🖼️";
  if (["pdf"].includes(ext)) return "📄";
  if (["md", "txt"].includes(ext)) return "📝";
  if (["csv", "xlsx", "json"].includes(ext)) return "📊";
  return "📎";
}

function fmtSize(size?: number): string {
  if (size == null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function FileRefChip({ ref: file }: { ref: FileRef }) {
  const title = file.path ? `${file.path}${file.size != null ? ` · ${fmtSize(file.size)}` : ""}` : undefined;
  return (
    <span
      className="inline-flex items-center gap-1 rounded border bg-muted px-2 py-0.5 text-xs"
      title={title}
      data-testid="file-ref-chip"
    >
      <span aria-hidden>{fileIcon(file.name)}</span>
      <span className="max-w-48 truncate">{file.name}</span>
      {file.path && <span className="text-muted-foreground">{file.path}</span>}
    </span>
  );
}
