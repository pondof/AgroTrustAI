import { ChevronLeft, ChevronRight, Eye, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { scoreColor } from "@/components/ui/ScoreGauge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DossieListItem } from "@/types";
import { formatBRL, formatDateTime } from "@/lib/utils";

interface DossieTableProps {
  items: DossieListItem[];
  isLoading?: boolean;
  page?: number;
  pages?: number;
  total?: number;
  onPageChange?: (page: number) => void;
}

export function DossieTable({ items, isLoading, page, pages, total, onPageChange }: DossieTableProps) {
  if (isLoading) return <LoadingSpinner label="Carregando dossiês…" />;

  if (items.length === 0) {
    return (
      <EmptyState
        title="Nenhum dossiê encontrado"
        description="Novos dossiês aparecerão aqui após a submissão de uma subscrição."
      />
    );
  }

  const showPager = Boolean(onPageChange && page && pages && pages > 1);

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>CAR</TableHead>
            <TableHead className="text-right">Valor</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Criado em</TableHead>
            <TableHead className="text-right">Ações</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((d) => (
            <TableRow key={d.dossie_id}>
              <TableCell className="font-medium">
                <Link to={`/dossies/${d.dossie_id}`} className="text-primary hover:underline">
                  {d.dossie_id}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{d.car_number}</TableCell>
              <TableCell className="text-right tabular-nums">{formatBRL(d.credit_amount_brl)}</TableCell>
              <TableCell className="text-right tabular-nums font-semibold" style={{ color: scoreColor(d.composite_score) }}>
                {d.composite_score === null ? "—" : Math.round(d.composite_score)}
              </TableCell>
              <TableCell>
                <StatusBadge status={d.verdict ?? d.status} />
              </TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(d.created_at)}</TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <Button asChild variant="ghost" size="icon" aria-label="Ver detalhes">
                    <Link to={`/dossies/${d.dossie_id}`}>
                      <Eye className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="ghost" size="icon" aria-label="Ver auditoria">
                    <Link to={`/dossies/${d.dossie_id}/audit`}>
                      <ShieldCheck className="h-4 w-4" />
                    </Link>
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {showPager && page && pages && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {total !== undefined && `${total} dossiê(s) · `}Página {page} de {pages}
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange?.(page - 1)}
            >
              <ChevronLeft className="h-4 w-4" /> Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= pages}
              onClick={() => onPageChange?.(page + 1)}
            >
              Próxima <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
