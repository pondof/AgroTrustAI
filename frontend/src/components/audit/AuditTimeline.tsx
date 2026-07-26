import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import type { AuditTrailEntry } from "@/types";
import { cn, formatDateTime, truncateHash } from "@/lib/utils";

import { AuditHashVerifier, EntryHashBadge } from "./AuditHashVerifier";

interface AuditTimelineProps {
  entries: AuditTrailEntry[];
}

/** Ícone (emoji) por tipo de evento de auditoria. */
export function eventIcon(eventType: string): string {
  const t = eventType.toLowerCase();
  if (t.includes("initiated")) return "🚀";
  if (t.includes("approved")) return "✅";
  if (t.includes("rejected")) return "❌";
  if (t.includes("agent")) return "🔍";
  if (t.startsWith("auth")) return "🔐";
  if (t.includes("pii") || t.includes("export")) return "📤";
  return "📝";
}

function CopyHashButton({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        void navigator.clipboard?.writeText(hash).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-xs text-muted-foreground hover:bg-muted"
      aria-label="Copiar hash completo"
      title="Copiar hash completo"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
      {truncateHash(hash, 12)}
    </button>
  );
}

export function AuditTimeline({ entries }: AuditTimelineProps) {
  if (entries.length === 0) {
    return (
      <EmptyState
        title="Sem eventos de auditoria"
        description="Nenhum evento foi registrado para este dossiê ainda."
      />
    );
  }

  // Mais recente no topo (o backend retorna em ordem de inserção: mais antigo → recente).
  const ordered = [...entries].reverse();

  return (
    <div className="space-y-4">
      <AuditHashVerifier entries={entries} />

      <ol className="relative space-y-1 border-l border-border pl-6">
        {ordered.map((entry) => (
          <li key={entry.event_id} className="relative">
            <span className="absolute -left-[31px] flex h-6 w-6 items-center justify-center rounded-full bg-card text-sm ring-4 ring-background">
              {eventIcon(entry.event_type)}
            </span>
            <details className="group rounded-md border bg-card">
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
                <span className="font-medium">{entry.event_type}</span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                    entry.outcome === "success"
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                      : entry.outcome === "failure"
                        ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                        : "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
                  )}
                >
                  {entry.outcome}
                </span>
                <span className="text-muted-foreground">{entry.subject}</span>
                <time className="text-xs text-muted-foreground">{formatDateTime(entry.timestamp)}</time>
                <div className="ml-auto flex items-center gap-2">
                  <CopyHashButton hash={entry.entry_hash} />
                  <EntryHashBadge entry={entry} />
                </div>
              </summary>
              <div className="border-t px-3 py-2">
                <p className="mb-1 text-xs font-semibold text-muted-foreground">Detalhes do evento</p>
                <pre className="max-h-64 overflow-auto rounded bg-muted p-2 text-xs">
                  {JSON.stringify(entry.details, null, 2)}
                </pre>
              </div>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}
