"""
AgroTrust AI – report-service: schemas Pydantic.

  - ReportRequest:  payload recebido do gateway (S2S) para gerar um relatório.
  - ReportMetadata: metadados do artefato gerado (id, timestamp, hash da cadeia,
                    assinatura), usados no rodapé do PDF e em logs de auditoria.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    """Solicitação de geração de relatório (enviada pelo gateway)."""

    dossie_id: str
    tenant_id: str
    requested_by: str
    report_type: str = Field(default="compliance", pattern="^(compliance|audit)$")


class ReportMetadata(BaseModel):
    """Metadados imutáveis de um relatório gerado."""

    report_id: str = Field(default_factory=lambda: f"RPT-{uuid.uuid4().hex[:12].upper()}")
    dossie_id: str
    tenant_id: str
    report_type: str
    generated_by: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    chain_head_hash: str = ""
    audit_entries: int = 0
    signed: bool = False
    signer_subject: str | None = None

    def display_generated_at(self) -> str:
        """Timestamp legível (UTC) para o rodapé do PDF."""
        try:
            return datetime.fromisoformat(self.generated_at).strftime("%d/%m/%Y %H:%M:%S UTC")
        except ValueError:  # pragma: no cover
            return self.generated_at
