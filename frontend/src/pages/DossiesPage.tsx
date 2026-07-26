import { useState } from "react";

import { DossieTable } from "@/components/dashboard/DossieTable";
import { NewDossieModal } from "@/components/dossie/NewDossieModal";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { useDossies } from "@/hooks/useDossies";

const STATUS_OPTIONS = [
  { value: "", label: "Todos os status" },
  { value: "initiated", label: "Iniciado" },
  { value: "approved", label: "Aprovado" },
  { value: "rejected", label: "Reprovado" },
  { value: "manual_review", label: "Análise Manual" },
];

const VERDICT_OPTIONS = [
  { value: "", label: "Todos os veredictos" },
  { value: "approved", label: "Aprovado" },
  { value: "rejected", label: "Reprovado" },
  { value: "manual_review", label: "Análise Manual" },
];

const selectClass =
  "flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function DossiesPage() {
  const { hasScope } = useAuth();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [verdict, setVerdict] = useState("");

  const query = useDossies({ page, limit: 20, status: status || undefined, verdict: verdict || undefined });
  const data = query.data;
  const canWrite = hasScope("subscription:write");

  const resetTo = (setter: (v: string) => void) => (value: string) => {
    setter(value);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Dossiês</h1>
          <p className="text-sm text-muted-foreground">Todas as subscrições do tenant.</p>
        </div>
        {canWrite && <NewDossieModal />}
      </div>

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="filter-status">Status</Label>
              <select
                id="filter-status"
                className={selectClass}
                value={status}
                onChange={(e) => resetTo(setStatus)(e.target.value)}
              >
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="filter-verdict">Veredicto</Label>
              <select
                id="filter-verdict"
                className={selectClass}
                value={verdict}
                onChange={(e) => resetTo(setVerdict)(e.target.value)}
              >
                {VERDICT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <DossieTable
            items={data?.items ?? []}
            isLoading={query.isLoading}
            page={data?.page}
            pages={data?.pages}
            total={data?.total}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>
    </div>
  );
}
