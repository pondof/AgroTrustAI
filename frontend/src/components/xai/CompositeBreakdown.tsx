import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { CATEGORICAL } from "@/lib/chartColors";

interface Weights {
  esg: number;
  financial: number;
  security: number;
}

interface CompositeBreakdownProps {
  esg: number | null;
  financial: number | null;
  security: number | null;
  weights?: Weights;
}

const DEFAULT_WEIGHTS: Weights = { esg: 0.35, financial: 0.45, security: 0.2 };

/**
 * Pizza da contribuição de cada agente ao score composto = peso × score. Usa os
 * pesos configurados do tenant quando fornecidos; senão, os pesos padrão do
 * VerdictEngine (0.35 / 0.45 / 0.20). Fatias com rótulo direto (identidade nunca
 * só por cor) + legenda.
 */
export function CompositeBreakdown({ esg, financial, security, weights }: CompositeBreakdownProps) {
  const w = weights ?? DEFAULT_WEIGHTS;
  const data = [
    { key: "esg", name: "ESG", weight: w.esg, score: esg ?? 0, contribution: w.esg * (esg ?? 0) },
    {
      key: "financial",
      name: "Financeiro",
      weight: w.financial,
      score: financial ?? 0,
      contribution: w.financial * (financial ?? 0),
    },
    {
      key: "security",
      name: "Segurança",
      weight: w.security,
      score: security ?? 0,
      contribution: w.security * (security ?? 0),
    },
  ];
  const total = data.reduce((acc, d) => acc + d.contribution, 0);

  if (total <= 0) {
    return <p className="text-sm text-muted-foreground">Sem scores para compor o breakdown.</p>;
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey="contribution"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={85}
            paddingAngle={2}
            isAnimationActive={false}
            labelLine={false}
          >
            {data.map((d, i) => (
              <Cell key={d.key} fill={CATEGORICAL[i % CATEGORICAL.length]} stroke="hsl(var(--card))" strokeWidth={2} />
            ))}
          </Pie>
          <Legend />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
        </PieChart>
      </ResponsiveContainer>

      <ul className="mt-2 space-y-1 text-xs">
        {data.map((d, i) => (
          <li key={d.key} className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ background: CATEGORICAL[i % CATEGORICAL.length] }}
                aria-hidden
              />
              {d.name}
            </span>
            <span className="tabular-nums text-muted-foreground">
              peso {d.weight} × {Math.round(d.score)} = {Math.round(d.contribution)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
