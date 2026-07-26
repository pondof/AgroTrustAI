import { AlertCircle } from "lucide-react";

import { RiskParamsForm } from "@/components/params/RiskParamsForm";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useRiskParams } from "@/hooks/useParams";

export function ParamsPage() {
  const params = useRiskParams();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Parâmetros de Risco</h1>
        <p className="text-sm text-muted-foreground">
          Ajuste os pesos e thresholds do motor de decisão do tenant.
        </p>
      </div>

      {params.isLoading ? (
        <LoadingSpinner fullPage label="Carregando parâmetros…" />
      ) : params.isError || !params.data ? (
        <EmptyState
          icon={AlertCircle}
          title="Não foi possível carregar os parâmetros"
          description="Verifique se você tem o escopo admin:params."
        />
      ) : (
        <RiskParamsForm initial={params.data} />
      )}
    </div>
  );
}
