import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { NEGATIVE, POSITIVE } from "@/lib/chartColors";
import type { ShapData } from "@/types";

interface ShapWaterfallProps {
  shap: ShapData;
}

interface Row {
  feature: string;
  value: number;
  valueLabel: string;
  color: string;
}

/**
 * Contribuições SHAP do modelo financeiro. Cada feature é uma barra divergente
 * (positivo eleva a predição, negativo reduz), ordenada por magnitude. O valor-base
 * é exibido como legenda numérica (ponto de partida do "waterfall").
 */
export function ShapWaterfall({ shap }: ShapWaterfallProps) {
  const rows: Row[] = Object.entries(shap.shap_values ?? {})
    .map(([feature, value]) => ({
      feature,
      value,
      valueLabel: value.toFixed(2),
      color: value >= 0 ? POSITIVE : NEGATIVE,
    }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Sem valores SHAP disponíveis.</p>;
  }

  const maxAbs = Math.max(0.01, ...rows.map((r) => Math.abs(r.value)));
  const height = Math.max(120, rows.length * 40 + 40);

  return (
    <div>
      <div className="mb-2 text-xs text-muted-foreground">
        Valor-base do modelo:{" "}
        <span className="font-medium text-foreground">
          {shap.base_value !== undefined ? shap.base_value.toFixed(3) : "—"}
        </span>
        {" · "}barras: contribuição de cada feature
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart layout="vertical" data={rows} margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
          <XAxis
            type="number"
            domain={[-maxAbs, maxAbs]}
            tickFormatter={(v: number) => v.toFixed(2)}
            fontSize={11}
            stroke="hsl(var(--muted-foreground))"
          />
          <YAxis type="category" dataKey="feature" width={150} fontSize={11} stroke="hsl(var(--muted-foreground))" />
          <ReferenceLine x={0} stroke="hsl(var(--border))" />
          <Tooltip
            cursor={{ fill: "hsl(var(--muted))", opacity: 0.3 }}
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Bar dataKey="value" isAnimationActive={false} radius={[4, 4, 4, 4]}>
            {rows.map((r) => (
              <Cell key={r.feature} fill={r.color} />
            ))}
            <LabelList
              dataKey="valueLabel"
              position="right"
              fontSize={10}
              fill="hsl(var(--muted-foreground))"
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
