import { useParams } from "react-router-dom";

import { DossieDetailView } from "@/components/dossie/DossieDetailPage";
import { EmptyState } from "@/components/ui/EmptyState";

export function DossieDetailPage() {
  const { dossieId } = useParams<{ dossieId: string }>();
  if (!dossieId) return <EmptyState title="Dossiê inválido" />;
  return <DossieDetailView dossieId={dossieId} />;
}
