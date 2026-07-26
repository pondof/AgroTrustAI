import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScoreGauge } from "@/components/ui/ScoreGauge";
import { statusStyle } from "@/components/ui/StatusBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AgentRationale, XaiDetail, XaiScores } from "@/types";

import { CompositeBreakdown } from "./CompositeBreakdown";
import { FactorsChart } from "./FactorsChart";
import { ShapWaterfall } from "./ShapWaterfall";

interface XAIPanelProps {
  xai: XaiDetail;
}

const AGENTS = [
  { key: "esg", label: "ESG", rationaleKey: "esg_rationale" },
  { key: "financial", label: "Financeiro", rationaleKey: "financial_rationale" },
  { key: "security", label: "Segurança", rationaleKey: "security_rationale" },
] as const;

function scoreFor(xai: XaiDetail, key: string): number | null {
  const fromBreakdown = xai.breakdown?.[key]?.score;
  if (fromBreakdown !== undefined && fromBreakdown !== null) return fromBreakdown;
  const scores = xai.rationale?.scores as XaiScores | undefined;
  const s = scores?.[key as keyof XaiScores];
  return s ?? null;
}

function AgentTab({ rationale, score, label }: { rationale: AgentRationale; score: number | null; label: string }) {
  const factors = rationale.factors ?? [];
  return (
    <div className="grid gap-6 md:grid-cols-[200px_1fr]">
      <div className="flex flex-col items-center gap-2">
        <ScoreGauge value={score} label={label} size={170} />
        {rationale.decision && (
          <p className="text-center text-sm">
            Decisão: <span className="font-semibold">{rationale.decision}</span>
          </p>
        )}
        {rationale.confidence !== undefined && (
          <p className="text-center text-xs text-muted-foreground">
            Confiança: {(rationale.confidence * 100).toFixed(0)}%
          </p>
        )}
      </div>
      <div>
        <h4 className="mb-2 text-sm font-semibold">Fatores da decisão</h4>
        {factors.length > 0 ? (
          <FactorsChart factors={factors} />
        ) : (
          <p className="text-sm text-muted-foreground">Nenhum fator estruturado reportado por este agente.</p>
        )}
      </div>
    </div>
  );
}

export function XAIPanel({ xai }: XAIPanelProps) {
  const verdict = xai.verdict ?? "initiated";
  const vStyle = statusStyle(verdict);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Explicabilidade (XAI)</CardTitle>
        <p className="text-sm text-muted-foreground">
          Todo resultado de agente é auditável — nenhum score é uma caixa-preta.
        </p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="composto">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="composto">Composto</TabsTrigger>
            {AGENTS.map((a) => (
              <TabsTrigger key={a.key} value={a.key}>
                {a.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="composto">
            <div className="grid gap-6 md:grid-cols-[1fr_1fr]">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Veredicto:</span>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${vStyle.badge}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${vStyle.dot}`} aria-hidden />
                    {vStyle.label}
                  </span>
                </div>
                <ScoreGauge value={xai.composite_score} label="Score Composto" size={180} />
                {xai.breakdown?.composite?.rejection_reasons &&
                  xai.breakdown.composite.rejection_reasons.length > 0 && (
                    <div className="rounded-md bg-red-500/10 p-3 text-sm">
                      <p className="mb-1 font-semibold text-red-700 dark:text-red-300">Motivos de reprovação</p>
                      <ul className="list-inside list-disc text-red-700 dark:text-red-300">
                        {xai.breakdown.composite.rejection_reasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
              </div>
              <div>
                <h4 className="mb-2 text-sm font-semibold">Contribuição por agente</h4>
                <CompositeBreakdown
                  esg={scoreFor(xai, "esg")}
                  financial={scoreFor(xai, "financial")}
                  security={scoreFor(xai, "security")}
                />
              </div>
            </div>
          </TabsContent>

          {AGENTS.map((a) => {
            const rationale = (xai.rationale?.[a.rationaleKey] as AgentRationale | undefined) ?? {};
            const score = scoreFor(xai, a.key);
            return (
              <TabsContent key={a.key} value={a.key}>
                <AgentTab rationale={rationale} score={score} label={a.label} />
                {a.key === "financial" && rationale.shap && (
                  <div className="mt-6">
                    <h4 className="mb-2 text-sm font-semibold">Contribuições SHAP</h4>
                    <ShapWaterfall shap={rationale.shap} />
                  </div>
                )}
              </TabsContent>
            );
          })}
        </Tabs>
      </CardContent>
    </Card>
  );
}
