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

import { impactColor, impactSign, NEGATIVE, POSITIVE } from "@/lib/chartColors";
import type { XaiFactor } from "@/types";

interface FactorsChartProps {
  factors: XaiFactor[];
}

interface Row {
  name: string;
  signed: number;
  weight: number;
  value: string;
  impact: string;
  color: string;
  sign: 1 | -1;
}

/**
 * Barras horizontais divergentes dos fatores de um agente. Comprimento = peso;
 * direção (direita/esquerda) e cor (verde/vermelho) = sinal do impacto. Direção +
 * rótulo do sinal garantem legibilidade sem depender só da cor.
 */
export function FactorsChart({ factors }: FactorsChartProps) {
  const rows: Row[] = factors.map((f) => {
    const sign = impactSign(f.impact);
    return {
      name: f.name,
      signed: Math.abs(f.weight) * sign,
      weight: f.weight,
      value: String(f.value),
      impact: String(f.impact),
      color: impactColor(f.impact),
      sign,
    };
  });

  const maxAbs = Math.max(0.01, ...rows.map((r) => Math.abs(r.signed)));
  const height = Math.max(120, rows.length * 44 + 40);

  return (
    <div>
      <div className="mb-2 flex items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: POSITIVE }} aria-hidden />
          Impacto positivo (→)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: NEGATIVE }} aria-hidden />
          Impacto negativo (←)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart layout="vertical" data={rows} margin={{ top: 4, right: 48, bottom: 4, left: 8 }}>
          <XAxis
            type="number"
            domain={[-maxAbs, maxAbs]}
            tickFormatter={(v: number) => Math.abs(v).toFixed(2)}
            fontSize={11}
            stroke="hsl(var(--muted-foreground))"
          />
          <YAxis
            type="category"
            dataKey="name"
            width={140}
            fontSize={11}
            stroke="hsl(var(--muted-foreground))"
          />
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
          <Bar dataKey="signed" isAnimationActive={false} radius={[4, 4, 4, 4]}>
            {rows.map((r) => (
              <Cell key={r.name} fill={r.color} />
            ))}
            <LabelList
              dataKey="impact"
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
