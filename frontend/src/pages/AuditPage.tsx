import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { AuditTimeline } from "@/components/audit/AuditTimeline";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useAuditTrail } from "@/hooks/useDossieDetail";

export function AuditPage() {
  const { dossieId } = useParams<{ dossieId: string }>();
  const audit = useAuditTrail(dossieId ?? "");

  if (!dossieId) return <EmptyState title="Dossiê inválido" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Auditoria</h1>
          <p className="text-sm text-muted-foreground">Trilha imutável do dossiê {dossieId}.</p>
        </div>
        <Button asChild variant="ghost" size="sm" className="gap-1.5">
          <Link to={`/dossies/${dossieId}`}>
            <ArrowLeft className="h-4 w-4" /> Voltar ao dossiê
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Eventos ({audit.data?.total ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {audit.isLoading ? (
            <LoadingSpinner label="Carregando trilha…" />
          ) : audit.isError || !audit.data ? (
            <EmptyState title="Trilha indisponível" description="Não foi possível carregar a auditoria." />
          ) : (
            <AuditTimeline entries={audit.data.entries} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
