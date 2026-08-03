import { useMemo } from 'react';
import { marked } from 'marked';

interface Props {
  content: string;
  onNavigate?: (path: string) => void;
  plainLinks?: boolean;
  /** 启用源行号锚点（Lxx），用于搜索跳转定位 */
  lineAnchors?: boolean;
}

function parseWikilink(raw: string) {
  const idx = raw.indexOf('|');
  const path = idx >= 0 ? raw.slice(0, idx).trim() : raw.trim();
  const label = idx >= 0 ? raw.slice(idx + 1).trim() : (path.split('/').pop() || path).replace(/\.md$/i, '');
  return { path, label };
}

function InlineTokens({ tokens, onNav, plain }: { tokens: any[]; onNav?: (path: string) => void; plain?: boolean }) {
  return <>{tokens.map((t, i) => {
    if (t.type === 'text') {
      const text = (t as any).text || '';
      const parts = text.split(/(\[\[[^\]]+\]\])/g);
      return <span key={i}>{parts.map((part: string, j: number) => {
        const m = part.match(/^\[\[([^\]]+)\]\]$/);
        if (m) {
          const { label } = parseWikilink(m[1]);
          if (plain) return <span key={j} className="text-muted-foreground">{label}</span>;
          return (
            <span
              key={j}
              className="wikilink text-sm cursor-pointer"
              onClick={() => onNav?.(m[1].split('|')[0]?.trim() || m[1].trim())}
            >
              {label}
            </span>
          );
        }
        return <span key={j}>{part}</span>;
      })}</span>;
    }
    if (t.type === 'strong') return <strong key={i}>{(t as any).text}</strong>;
    if (t.type === 'em') return <em key={i}>{(t as any).text}</em>;
    if (t.type === 'del') return <del key={i}>{(t as any).text}</del>;
    if (t.type === 'codespan') return <code key={i} className="px-1 py-0.5 rounded text-xs bg-muted">{(t as any).text}</code>;
    if (t.type === 'link') return <a key={i} href={(t as any).href} className="text-sm text-blue-500 hover:underline">{(t as any).text}</a>;
    if (t.type === 'image') return <img key={i} src={(t as any).href} alt={(t as any).text} className="max-w-full rounded" />;
    if (t.type === 'br') return <br key={i} />;
    return <span key={i}>{(t as any).raw || ''}</span>;
  })}</>;
}

const headingCls: Record<number, string> = {
  1: 'text-xl font-bold border-b border-border pb-1 mb-3 mt-6',
  2: 'text-lg font-semibold mt-5 mb-2',
  3: 'text-base font-semibold mt-4 mb-1',
  4: 'text-sm font-semibold mt-3 mb-1',
  5: 'text-sm font-medium mt-2 mb-1',
  6: 'text-xs font-medium mt-2 mb-1',
};

/**
 * 将源文本按行拆分，顺序扫描 tokens（marked 的 tokens 按源码顺序排列），
 * 计算每个 token 在源文本中的起始行号。
 * 返回 Map<tokenIndex, lineNumber>。
 */
function computeLineMap(rawContent: string, tokens: any[]): Map<number, number> {
  const lineMap = new Map<number, number>();
  const lines = rawContent.split('\n');
  // 累积每行字符偏移（含换行符）
  const offsets: number[] = [0];
  let acc = 0;
  for (let i = 0; i < lines.length; i++) {
    acc += lines[i].length + 1; // +1 for \n
    offsets.push(acc);
  }
  /** 根据字符偏移量返回行号（1-based） */
  const offsetToLine = (charOffset: number): number => {
    let lo = 0, hi = offsets.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (offsets[mid] <= charOffset) lo = mid + 1;
      else hi = mid;
    }
    return Math.max(1, lo);
  };
  // 顺序扫描：维护搜索起点指针，避免 indexOf 重复内容问题
  let searchFrom = 0;
  tokens.forEach((token: any, idx: number) => {
    const raw = token.raw || '';
    if (!raw || typeof (token as any).type !== 'string') return;
    // 从上次位置后查找，保证顺序正确
    const foundAt = rawContent.indexOf(raw, searchFrom);
    if (foundAt >= 0) {
      lineMap.set(idx, offsetToLine(foundAt));
      searchFrom = foundAt + raw.length;
    }
  });
  return lineMap;
}

export default function MarkdownRenderer({ content, onNavigate, plainLinks, lineAnchors = false }: Props) {
  const tokens = useMemo(() => marked.lexer(content), [content]);
  const lineMap = useMemo(() => lineAnchors ? computeLineMap(content, tokens) : new Map(), [content, tokens, lineAnchors]);

  const wrapWithAnchor = (node: React.ReactNode, key: number) => {
    if (!lineAnchors) return node;
    const line = lineMap.get(key);
    if (!line) return node;
    return (
      <span id={`L${line}`} className="scroll-mt-20 block search-line-anchor transition-colors duration-500">
        {node}
      </span>
    );
  };

  return (
    <div className="md-content">
      {tokens.map((token, i) => {
        switch (token.type) {
          case 'heading': {
            const t = token as any;
            const cls = headingCls[t.depth] || '';
            const { text } = t;
            const headings: Record<number, React.ReactNode> = {
              1: <h1 key={i} className={cls}>{text}</h1>,
              2: <h2 key={i} className={cls}>{text}</h2>,
              3: <h3 key={i} className={cls}>{text}</h3>,
              4: <h4 key={i} className={cls}>{text}</h4>,
              5: <h5 key={i} className={cls}>{text}</h5>,
              6: <h6 key={i} className={cls}>{text}</h6>,
            };
            return wrapWithAnchor(headings[t.depth] || headings[6], i);
          }
          case 'paragraph': {
            const t = token as any;
            return wrapWithAnchor(
              <p key={i} className="mb-2 text-sm leading-relaxed">
                <InlineTokens tokens={t.tokens} onNav={onNavigate} plain={plainLinks} />
              </p>,
              i
            );
          }
          case 'code': {
            const t = token as any;
            return wrapWithAnchor(
              <pre key={i} className="bg-muted rounded-lg p-3 my-2 text-xs overflow-x-auto border border-border">
                <code>{t.text}</code>
              </pre>,
              i
            );
          }
          case 'list': {
            const t = token as any;
            const Tag = t.ordered ? 'ol' : 'ul';
            return wrapWithAnchor(
              <Tag key={i} className={`mb-2 pl-5 text-sm ${t.ordered ? 'list-decimal' : 'list-disc'}`}>
                {t.items.map((item: any, j: number) => (
                  <li key={j} className="mb-0.5"><InlineTokens tokens={item.tokens} onNav={onNavigate} plain={plainLinks} /></li>
                ))}
              </Tag>,
              i
            );
          }
          case 'table': {
            const t = token as any;
            return wrapWithAnchor(
              <div key={i} className="overflow-x-auto mb-3">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr>{t.header.map((h: any, j: number) => (
                      <th key={j} className="border border-border px-3 py-2 text-left font-semibold bg-muted">{h.text}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {t.rows.map((row: any[], j: number) => (
                      <tr key={j}>{row.map((cell: any, k: number) => (
                        <td key={k} className="border border-border px-3 py-1.5">{cell.text}</td>
                      ))}</tr>
                    ))}
                  </tbody>
                </table>
              </div>,
              i
            );
          }
          case 'blockquote': {
            const t = token as any;
            return wrapWithAnchor(
              <blockquote key={i} className="border-l-3 border-blue-500 pl-4 mb-2 text-sm text-muted-foreground">
                {t.tokens ? <InlineTokens tokens={t.tokens} onNav={onNavigate} plain={plainLinks} /> : t.text}
              </blockquote>,
              i
            );
          }
          case 'hr':
            return wrapWithAnchor(<hr key={i} className="border-t border-border my-4" />, i);
          case 'space':
            return null;
          case 'html': {
            const t = token as any;
            return wrapWithAnchor(
              <div key={i} className="text-sm mb-2" dangerouslySetInnerHTML={{ __html: t.text }} />,
              i
            );
          }
          default:
            return null;
        }
      })}
    </div>
  );
}
