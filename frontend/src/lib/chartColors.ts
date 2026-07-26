/**
 * Paleta dos gráficos (Recharts). Hexes validados da paleta de referência do
 * design-system de data-viz. Categóricos usam os 3 primeiros slots (blue/orange/
 * aqua), que passam o gate de todos-os-pares. Polaridade (impacto +/−) usa
 * verde/vermelho SEMPRE acompanhada de direção da barra + rótulo do sinal — nunca
 * cor sozinha, para leitores com daltonismo.
 */

export const CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a"] as const;

export const POSITIVE = "#10b981"; // emerald-500 — contribuição que eleva o score
export const NEGATIVE = "#e34948"; // red — contribuição que reduz o score
export const NEUTRAL = "#94a3b8"; // slate-400

/** Sinal do impacto de um fator XAI (string "positive"/"negative" ou número). */
export function impactSign(impact: string | number | null | undefined): 1 | -1 {
  if (typeof impact === "number") return impact >= 0 ? 1 : -1;
  if (typeof impact === "string" && impact.toLowerCase().includes("neg")) return -1;
  return 1;
}

export function impactColor(impact: string | number | null | undefined): string {
  return impactSign(impact) === 1 ? POSITIVE : NEGATIVE;
}
