import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { extractErrorMessage } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { statusStyle } from "@/components/ui/StatusBadge";
import { useUpdateParams } from "@/hooks/useParams";
import type { RiskParams, RiskParamsRequest } from "@/types";
import { cn } from "@/lib/utils";

interface RiskParamsFormProps {
  initial: RiskParams;
}

const WEIGHT_TOLERANCE = 1e-6;

const WEIGHTS = [
  { key: "w_esg", label: "Peso ESG" },
  { key: "w_financial", label: "Peso Financeiro" },
  { key: "w_security", label: "Peso Segurança" },
] as const;

type WeightKey = (typeof WEIGHTS)[number]["key"];

function previewVerdict(score: number, approve: number, manual: number): { verdict: string; key: string } {
  if (score >= approve) return { verdict: "APROVADO", key: "approved" };
  if (score >= manual) return { verdict: "ANÁLISE MANUAL", key: "manual_review" };
  return { verdict: "REPROVADO", key: "rejected" };
}

export function RiskParamsForm({ initial }: RiskParamsFormProps) {
  const mutation = useUpdateParams();
  const [form, setForm] = useState<RiskParamsRequest>({
    w_esg: initial.w_esg,
    w_financial: initial.w_financial,
    w_security: initial.w_security,
    approve_threshold: initial.approve_threshold,
    manual_threshold: initial.manual_threshold,
    max_dti: initial.max_dti,
    max_credit_multiplier: initial.max_credit_multiplier,
  });
  const [testScore, setTestScore] = useState(650);

  const sum = form.w_esg + form.w_financial + form.w_security;
  const sumValid = Math.abs(sum - 1) <= WEIGHT_TOLERANCE;
  const thresholdsValid = form.manual_threshold <= form.approve_threshold;
  const canSave = sumValid && thresholdsValid && !mutation.isPending;

  const setWeight = (key: WeightKey, value: number) => {
    const clamped = Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
    setForm((f) => ({ ...f, [key]: Math.round(clamped * 100) / 100 }));
  };

  const setField = (key: keyof RiskParamsRequest, value: number) => {
    setForm((f) => ({ ...f, [key]: Number.isFinite(value) ? value : 0 }));
  };

  const preview = previewVerdict(testScore, form.approve_threshold, form.manual_threshold);
  const previewStyle = statusStyle(preview.key);

  const handleSubmit = () => {
    if (!canSave) return;
    mutation.mutate(form, {
      onSuccess: () => {
        toast.success("Parâmetros atualizados. Próximos dossiês usarão os novos pesos.");
      },
      onError: (error) => {
        toast.error(extractErrorMessage(error, "Falha ao salvar os parâmetros."));
      },
    });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pesos do Score Composto</CardTitle>
          <p className="text-sm text-muted-foreground">
            A soma dos três pesos deve ser exatamente 1.00.
          </p>
        </CardHeader>
        <CardContent className="space-y-6">
          {WEIGHTS.map(({ key, label }) => (
            <div key={key} className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor={key}>{label}</Label>
                <Input
                  id={`${key}-input`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={form[key]}
                  aria-label={label}
                  onChange={(e) => setWeight(key, Number.parseFloat(e.target.value))}
                  className="h-8 w-24 text-right tabular-nums"
                />
              </div>
              <Slider
                id={key}
                min={0}
                max={1}
                step={0.01}
                value={[form[key]]}
                onValueChange={([v]) => setWeight(key, v)}
              />
            </div>
          ))}

          <div
            className={cn(
              "flex items-center gap-2 rounded-md border p-3 text-sm font-medium",
              sumValid
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
            )}
            role="status"
          >
            {sumValid ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
            <span className="tabular-nums">
              {form.w_esg.toFixed(2)} + {form.w_financial.toFixed(2)} + {form.w_security.toFixed(2)} ={" "}
              {sum.toFixed(2)} {sumValid ? "✓" : "✗ (deve somar 1.00)"}
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="approve_threshold">Threshold de aprovação</Label>
              <Input
                id="approve_threshold"
                type="number"
                min={0}
                max={1000}
                step={1}
                value={form.approve_threshold}
                onChange={(e) => setField("approve_threshold", Number.parseFloat(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manual_threshold">Threshold de análise manual</Label>
              <Input
                id="manual_threshold"
                type="number"
                min={0}
                max={1000}
                step={1}
                value={form.manual_threshold}
                onChange={(e) => setField("manual_threshold", Number.parseFloat(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max_dti">DTI máximo</Label>
              <Input
                id="max_dti"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={form.max_dti}
                onChange={(e) => setField("max_dti", Number.parseFloat(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max_credit_multiplier">Multiplicador de crédito máx.</Label>
              <Input
                id="max_credit_multiplier"
                type="number"
                min={0}
                step={0.5}
                value={form.max_credit_multiplier}
                onChange={(e) => setField("max_credit_multiplier", Number.parseFloat(e.target.value))}
              />
            </div>
          </div>

          {!thresholdsValid && (
            <p className="flex items-center gap-1.5 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="h-4 w-4" />
              O threshold de análise manual não pode exceder o de aprovação.
            </p>
          )}

          <Button onClick={handleSubmit} disabled={!canSave} className="w-full">
            {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Salvar parâmetros
          </Button>
        </CardContent>
      </Card>

      <Card className="h-fit">
        <CardHeader>
          <CardTitle className="text-base">Prévia da decisão</CardTitle>
          <p className="text-sm text-muted-foreground">
            Simule o veredicto de um score composto com os thresholds atuais.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="test-score">Score composto de teste</Label>
              <span className="text-sm font-semibold tabular-nums">{testScore}</span>
            </div>
            <Slider
              id="test-score"
              min={0}
              max={1000}
              step={10}
              value={[testScore]}
              onValueChange={([v]) => setTestScore(v)}
            />
          </div>
          <div className="rounded-md border p-4 text-center">
            <p className="text-sm text-muted-foreground">
              Com esses pesos e thresholds, um score composto de{" "}
              <span className="font-semibold text-foreground">{testScore}</span> seria:
            </p>
            <span
              className={cn(
                "mt-2 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold",
                previewStyle.badge,
              )}
            >
              <span className={cn("h-2 w-2 rounded-full", previewStyle.dot)} aria-hidden />
              {preview.verdict}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
