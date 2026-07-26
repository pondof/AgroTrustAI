import { DossieTable } from "@/components/dashboard/DossieTable";
import { Card, CardContent } from "@/components/ui/card";
import { useDossies } from "@/hooks/useDossies";

/** Índice de auditoria: escolha um dossiê para inspecionar sua trilha (ícone de escudo). */
export function AuditIndexPage() {
  const query = useDossies({ page: 1, limit: 20 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Auditoria</h1>
        <p className="text-sm text-muted-foreground">
          Selecione um dossiê (ícone de escudo) para ver sua trilha imutável.
        </p>
      </div>
      <Card>
        <CardContent className="p-4">
          <DossieTable items={query.data?.items ?? []} isLoading={query.isLoading} />
        </CardContent>
      </Card>
    </div>
  );
}
