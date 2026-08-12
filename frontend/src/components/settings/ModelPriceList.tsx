import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { ProviderInfo } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** 模型单价编辑（F1，2026-08-12）：设置页每模型 input/output_price 输入 + 保存 */
export function ModelPriceList() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [prices, setPrices] = useState<Record<number, { input: string; output: string }>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api
      .listProviders()
      .then((r) => {
        setProviders(r.providers);
        const init: Record<number, { input: string; output: string }> = {};
        r.providers.forEach((p) =>
          p.models.forEach((m) => {
            init[m.id] = { input: String(m.input_price ?? 0), output: String(m.output_price ?? 0) };
          }),
        );
        setPrices(init);
      })
      .catch(() => setMsg("加载模型列表失败"));
  }, []);

  const save = async (modelId: number, input: string, output: string) => {
    const i = Number(input);
    const o = Number(output);
    if (i < 0 || o < 0 || Number.isNaN(i) || Number.isNaN(o)) {
      setMsg("单价必须为不小于 0 的数字");
      return;
    }
    setSaving(true);
    try {
      await api.updateModelPrice(modelId, i, o);
      setMsg(`已保存并生效（模型 ${modelId}）`);
    } catch {
      setMsg("保存失败（模型不存在）");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3" data-testid="model-price-list">
      <div className="text-sm font-medium">模型单价（元/千 token）</div>
      {providers.map((p) => (
        <div key={p.id} className="rounded border p-3">
          <div className="font-medium">{p.name}</div>
          {p.models.map((m) => {
            const cur = prices[m.id] ?? { input: "0", output: "0" };
            return (
              <div key={m.id} className="mt-1 flex items-center gap-2" data-testid={`price-row-${m.id}`}>
                <span className="w-44 truncate text-sm">{m.name}</span>
                <Input
                  className="h-8 w-24"
                  type="number"
                  step="0.001"
                  min="0"
                  aria-label={`${m.name} 输入单价`}
                  value={cur.input}
                  onChange={(e) => setPrices((s) => ({ ...s, [m.id]: { ...cur, input: e.target.value } }))}
                />
                <Input
                  className="h-8 w-24"
                  type="number"
                  step="0.001"
                  min="0"
                  aria-label={`${m.name} 输出单价`}
                  value={cur.output}
                  onChange={(e) => setPrices((s) => ({ ...s, [m.id]: { ...cur, output: e.target.value } }))}
                />
                <Button size="sm" disabled={saving} onClick={() => save(m.id, cur.input, cur.output)}>
                  保存
                </Button>
              </div>
            );
          })}
        </div>
      ))}
      {msg && <div className="text-sm text-muted-foreground" data-testid="price-msg">{msg}</div>}
    </div>
  );
}
