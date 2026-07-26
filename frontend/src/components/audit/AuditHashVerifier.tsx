import { sha3_256 } from "js-sha3";
import { ShieldAlert, ShieldCheck } from "lucide-react";

import type { AuditTrailEntry } from "@/types";
import { cn } from "@/lib/utils";

/**
 * Recomputa o SHA-3-256 de uma entrada de auditoria no cliente e compara com o
 * entry_hash do backend.
 *
 * Nota: a Web Crypto API (crypto.subtle) NÃO implementa SHA-3 — apenas SHA-1/2.
 * Por isso usamos js-sha3 (FIPS-202), idêntico ao hashlib.sha3_256 do backend.
 * Hasheamos a string canônica fornecida pelo gateway (a mesma sobre a qual o
 * backend calculou o hash), garantindo comparação byte-a-byte.
 */
export function verifyEntryHash(entry: AuditTrailEntry): boolean {
  if (!entry.canonical || !entry.entry_hash) return false;
  return sha3_256(entry.canonical) === entry.entry_hash;
}

export function EntryHashBadge({ entry, className }: { entry: AuditTrailEntry; className?: string }) {
  const ok = verifyEntryHash(entry);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        ok
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
          : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
        className,
      )}
      data-testid={ok ? "hash-verified" : "hash-invalid"}
      title={ok ? "Hash SHA-3-256 conferido no cliente" : "Hash não confere — possível adulteração"}
    >
      {ok ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
      {ok ? "Verificado ✓" : "Inválido ✗"}
    </span>
  );
}

interface ChainVerifierProps {
  entries: AuditTrailEntry[];
}

/** Resumo de integridade: quantas entradas conferem o hash recomputado. */
export function AuditHashVerifier({ entries }: ChainVerifierProps) {
  const verified = entries.filter(verifyEntryHash).length;
  const total = entries.length;
  const allOk = total > 0 && verified === total;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border p-3 text-sm font-medium",
        allOk
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
      )}
      role="status"
    >
      {allOk ? <ShieldCheck className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />}
      {total === 0
        ? "Sem entradas para verificar."
        : allOk
          ? `Cadeia íntegra: ${verified}/${total} entradas com SHA-3-256 conferido no cliente.`
          : `Atenção: ${verified}/${total} entradas conferem — ${total - verified} com hash divergente.`}
    </div>
  );
}
