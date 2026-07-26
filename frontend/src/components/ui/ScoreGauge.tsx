import { PolarAngleAxis, RadialBar, RadialBarChart } from "recharts";

import { cn } from "@/lib/utils";

interface ScoreGaugeProps {
  value: number | null | undefined;
  label?: string;
  size?: number;
  max?: number;
}

/** Cor por faixa do score (0–1000): alto=verde, médio=laranja, baixo=vermelho. */
export function scoreColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "#94a3b8"; // slate-400
  if (value >= 600) return "#10b981"; // emerald-500
  if (value >= 450) return "#f97316"; // orange-500
  return "#ef4444"; // red-500
}

/** Gauge semicircular (RadialBarChart) 0–max, com cor por faixa. */
export function ScoreGauge({ value, label, size = 160, max = 1000 }: ScoreGaugeProps) {
  const numeric = value ?? 0;
  const color = scoreColor(value);
  const data = [{ name: label ?? "score", value: numeric }];
  const height = size * 0.62;

  return (
    <div className="flex flex-col items-center" data-testid="score-gauge">
      <div className="relative" style={{ width: size, height }}>
        <RadialBarChart
          width={size}
          height={size}
          cx={size / 2}
          cy={size / 2}
          innerRadius={size * 0.36}
          outerRadius={size * 0.5}
          barSize={size * 0.14}
          startAngle={180}
          endAngle={0}
          data={data}
        >
          <PolarAngleAxis type="number" domain={[0, max]} angleAxisId={0} tick={false} />
          <RadialBar
            background={{ fill: "hsl(var(--muted))" }}
            dataKey="value"
            cornerRadius={size * 0.07}
            fill={color}
            angleAxisId={0}
            isAnimationActive={false}
          />
        </RadialBarChart>
        <div
          className="absolute inset-x-0 flex flex-col items-center"
          style={{ top: size * 0.28 }}
        >
          <span className="text-2xl font-bold tabular-nums" style={{ color }}>
            {value === null || value === undefined ? "—" : Math.round(value)}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">/ {max}</span>
        </div>
      </div>
      {label && <span className={cn("mt-1 text-sm font-medium text-muted-foreground")}>{label}</span>}
    </div>
  );
}
