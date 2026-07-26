import { AlertCircle, ArrowLeft, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { AuditTimeline } from "@/components/audit/AuditTimeline";
import { ReportRequestButton } from "@/components/reports/ReportRequestButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { XAIPanel } from "@/components/xai/XAIPanel";
import { useAuth } from "@/hooks/useAuth";
import { useAuditTrail, useDossieDetail, useDossieXai } from "@/hooks/useDossieDetail";

import { DossieDetailCard } from "./DossieDetailCard";

interface DossieDetailViewProps {
  dossieId: string;
}

/** Composição do detalhe de um dossiê: dados + XAI + auditoria + relatório. */
export function DossieDetailView({ dossieId }: DossieDetailViewProps) {
  const { hasScope } = useAuth();
  const detail = useDossieDetail(dossieId);
  const xai = useDossieXai(dossieId);
  const audit = useAuditTrail(dossieId);
  const canReadAudit = hasScope("audit:read");

  if (detail.isLoading) return <LoadingSpinner fullPage label="Carregando dossiê…" />;

  if (detail.isError || !detail.data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Dossiê não encontrado"
        description="O dossiê não existe ou você não tem acesso a ele."
        action={
          <Button asChild variant="outline">
            <Link to="/dossies">Voltar aos dossiês</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="gap-1.5">
          <Link to="/dossies">
            <ArrowLeft className="h-4 w-4" /> Dossiês
          </Link>
        </Button>
        <div className="flex items-center gap-2">
          {canReadAudit && (
            <Button asChild variant="outline" className="gap-2">
              <Link to={`/dossies/${dossieId}/audit`}>
                <ShieldCheck className="h-4 w-4" /> Auditoria
              </Link>
            </Button>
          )}
          <ReportRequestButton dossieId={dossieId} />
        </div>
      </div>

      <DossieDetailCard dossie={detail.data} />

      {xai.isLoading ? (
        <LoadingSpinner label="Carregando XAI…" />
      ) : xai.data ? (
        <XAIPanel xai={xai.data} />
      ) : null}

      {canReadAudit && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Trilha de Auditoria</CardTitle>
          </CardHeader>
          <CardContent>
            {audit.isLoading ? (
              <LoadingSpinner label="Carregando auditoria…" />
            ) : audit.data ? (
              <AuditTimeline entries={audit.data.entries} />
            ) : (
              <EmptyState title="Sem trilha de auditoria" />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
