import type { ReactNode } from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ScoreGauge } from "@/components/ui/ScoreGauge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { DossieDetail } from "@/types";
import { formatBRL, formatDateTime } from "@/lib/utils";

interface DossieDetailCardProps {
  dossie: DossieDetail;
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

export function DossieDetailCard({ dossie }: DossieDetailCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{dossie.dossie_id}</h2>
          <p className="text-sm text-muted-foreground">{dossie.car_number}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={dossie.status} />
          {dossie.verdict && <StatusBadge status={dossie.verdict} />}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          <Fact label="Área" value={`${dossie.property_area_ha} ha`} />
          <Fact label="Finalidade" value={dossie.credit_purpose} />
          <Fact label="Valor solicitado" value={formatBRL(dossie.credit_amount_brl)} />
          <Fact label="Valor aprovado" value={formatBRL(dossie.approved_amount_brl)} />
          <Fact label="Criado em" value={formatDateTime(dossie.created_at)} />
          <Fact label="Atualizado em" value={formatDateTime(dossie.updated_at)} />
          {dossie.processing_time_ms !== null && (
            <Fact label="Tempo de proc." value={`${dossie.processing_time_ms} ms`} />
          )}
        </dl>

        {dossie.rejection_reasons.length > 0 && (
          <div className="rounded-md bg-red-500/10 p-3 text-sm">
            <p className="mb-1 font-semibold text-red-700 dark:text-red-300">Motivos de reprovação</p>
            <ul className="list-inside list-disc text-red-700 dark:text-red-300">
              {dossie.rejection_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 rounded-lg border p-4 sm:grid-cols-4">
          <ScoreGauge value={dossie.esg_score} label="ESG" size={140} />
          <ScoreGauge value={dossie.financial_score} label="Financeiro" size={140} />
          <ScoreGauge value={dossie.security_score} label="Segurança" size={140} />
          <ScoreGauge value={dossie.composite_score} label="Composto" size={140} />
        </div>
      </CardContent>
    </Card>
  );
}
