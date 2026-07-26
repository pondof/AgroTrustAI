import { CheckCircle2, Clock, FileText, XCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { statusStyle } from "@/components/ui/StatusBadge";
import type { DossieListItem } from "@/types";
import { formatDateTime } from "@/lib/utils";

interface RecentActivityProps {
  items: DossieListItem[];
}

function iconFor(status: string) {
  switch (status) {
    case "approved":
      return CheckCircle2;
    case "rejected":
      return XCircle;
    case "manual_review":
      return Clock;
    default:
      return FileText;
  }
}

/**
 * Atividade recente do tenant. Como não há endpoint global de auditoria (apenas
 * por dossiê), derivamos a atividade dos dossiês mais recentes — a projeção já
 * carregada pelo dashboard. Cada item liga para o detalhe do dossiê.
 */
export function RecentActivity({ items }: RecentActivityProps) {
  const recent = items.slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Atividade Recente</CardTitle>
      </CardHeader>
      <CardContent>
        {recent.length === 0 ? (
          <EmptyState title="Sem atividade" description="Nenhum dossiê recente." />
        ) : (
          <ul className="space-y-3">
            {recent.map((d) => {
              const key = d.verdict ?? d.status;
              const style = statusStyle(key);
              const Icon = iconFor(key);
              return (
                <li key={d.dossie_id} className="flex items-center gap-3">
                  <div className={`flex h-8 w-8 items-center justify-center rounded-full ${style.badge}`}>
                    <Icon className="h-4 w-4" aria-hidden />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/dossies/${d.dossie_id}`}
                      className="text-sm font-medium text-primary hover:underline"
                    >
                      {d.dossie_id}
                    </Link>
                    <div className="truncate text-xs text-muted-foreground">
                      {style.label} · {d.car_number}
                    </div>
                  </div>
                  <time className="whitespace-nowrap text-xs text-muted-foreground">
                    {formatDateTime(d.updated_at ?? d.created_at)}
                  </time>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
