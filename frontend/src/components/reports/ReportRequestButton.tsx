import { FileDown, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { extractErrorMessage } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useGenerateReport } from "@/hooks/useReport";

interface ReportRequestButtonProps {
  dossieId: string;
}

export function ReportRequestButton({ dossieId }: ReportRequestButtonProps) {
  const mutation = useGenerateReport(dossieId);

  const handleClick = () => {
    mutation.mutate(undefined, {
      onSuccess: () => toast.success("Relatório PDF gerado e baixado."),
      onError: (error) => toast.error(extractErrorMessage(error, "Falha ao gerar o relatório PDF.")),
    });
  };

  return (
    <Button variant="outline" onClick={handleClick} disabled={mutation.isPending} className="gap-2">
      {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
      Gerar Relatório PDF
    </Button>
  );
}
