"""
AgroTrust AI – Agregação e renderização do relatório M1.

Métricas reportadas:
  • Distribuição de veredictos (aprovado / revisão manual / rejeitado / erros)
  • % de XAI completo (deve ser 100% para passar)
  • Tempo médio, p95 e p99 de processamento
  • Lista de falhas (até 10 primeiras; resumo no fim)
  • Status final: PASSOU / FALHOU com motivos
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass, field
from typing import IO

from scripts.m1.runner import M1Result


@dataclass(slots=True)
class M1Report:
    total: int
    approved_actual: int
    manual_review_actual: int
    rejected_actual: int
    errors: int
    xai_complete_count: int
    avg_processing_ms: float
    p95_processing_ms: float
    p99_processing_ms: float
    failures: list[tuple[str, list[str], str | None]] = field(default_factory=list)
    category_mismatch: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def xai_complete_pct(self) -> float:
        return 100.0 * self.xai_complete_count / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        return self.errors == 0 and self.xai_complete_pct == 100.0 and not self.failures


def _percentile(sorted_vals: list[int], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return float(sorted_vals[k])


def aggregate(results: list[M1Result]) -> M1Report:
    """Computa as métricas agregadas sobre a lista de resultados."""
    times = [r.processing_time_ms for r in results]
    sorted_times = sorted(times)

    approved = sum(1 for r in results if r.verdict and r.verdict.verdict == "approved")
    manual = sum(1 for r in results if r.verdict and r.verdict.verdict == "manual_review")
    rejected = sum(1 for r in results if r.verdict and r.verdict.verdict == "rejected")
    errors = sum(1 for r in results if r.error is not None or r.verdict is None)

    xai_complete = sum(
        1
        for r in results
        if r.verdict
        and isinstance(r.verdict.xai_consolidated_rationale, dict)
        and all(
            k in r.verdict.xai_consolidated_rationale
            for k in ("scores", "esg_rationale", "financial_rationale", "security_rationale")
        )
    )

    failures = [(r.scenario.dossie_id, r.validation_errors, r.error) for r in results if r.validation_errors or r.error]

    category_mismatch: list[tuple[str, str, str]] = []
    for r in results:
        actual = r.verdict.verdict if r.verdict else "error"
        if actual != r.scenario.expected_verdict:
            category_mismatch.append((r.scenario.dossie_id, r.scenario.expected_verdict, actual))

    return M1Report(
        total=len(results),
        approved_actual=approved,
        manual_review_actual=manual,
        rejected_actual=rejected,
        errors=errors,
        xai_complete_count=xai_complete,
        avg_processing_ms=statistics.mean(times) if times else 0.0,
        p95_processing_ms=_percentile(sorted_times, 0.95),
        p99_processing_ms=_percentile(sorted_times, 0.99),
        failures=failures,
        category_mismatch=category_mismatch,
    )


def render_report(report: M1Report, stream: IO[str] = sys.stdout) -> None:
    """Renderiza o relatório em texto plano (CLI-friendly)."""
    sep_top = "=" * 72
    sep_mid = "-" * 72
    lines: list[str] = [
        sep_top,
        "  Marco M1 -- Validacao de 50 Dossies",
        sep_top,
        f"  Total processados:        {report.total:3d}",
        f"  Aprovados:                {report.approved_actual:3d}",
        f"  Revisao manual:           {report.manual_review_actual:3d}",
        f"  Rejeitados:               {report.rejected_actual:3d}",
        f"  Erros de execucao:        {report.errors:3d}",
        sep_mid,
        f"  XAI completo:             {report.xai_complete_count}/{report.total} ({report.xai_complete_pct:.1f}%)",
        f"  Tempo medio:              {report.avg_processing_ms:.0f} ms",
        f"  P95 processamento:        {report.p95_processing_ms:.0f} ms",
        f"  P99 processamento:        {report.p99_processing_ms:.0f} ms",
        sep_mid,
    ]

    if report.category_mismatch:
        lines.append(f"  Veredictos divergentes do esperado: {len(report.category_mismatch)}")
        for dossie_id, expected, actual in report.category_mismatch[:10]:
            lines.append(f"    - {dossie_id}: esperado={expected} obtido={actual}")
        if len(report.category_mismatch) > 10:
            lines.append(f"    ... +{len(report.category_mismatch) - 10} adicional")
        lines.append(sep_mid)

    if report.failures:
        lines.append(f"  Falhas de validacao: {len(report.failures)}")
        for dossie_id, val_errs, exec_err in report.failures[:10]:
            msg = "; ".join(val_errs) if val_errs else (exec_err or "(falha de execucao)")
            lines.append(f"    - {dossie_id}: {msg}")
        if len(report.failures) > 10:
            lines.append(f"    ... +{len(report.failures) - 10} adicional")
        lines.append(sep_mid)

    status = "PASSOU" if report.passed else "FALHOU"
    lines.append(f"  Status final: {status}")
    if not report.passed:
        if report.xai_complete_pct < 100.0:
            lines.append(f"    Motivo: XAI incompleto em {report.total - report.xai_complete_count} decisoes")
        if report.errors:
            lines.append(f"    Motivo: {report.errors} erros de execucao do orquestrador")
        if report.failures:
            lines.append(f"    Motivo: {len(report.failures)} falhas de validacao")
    lines.append(sep_top)

    stream.write("\n".join(lines) + "\n")
    stream.flush()
