"""
AgroTrust AI – report-service (FastAPI).

Gera relatórios PDF (compliance LGPD/Bacen e trilha de auditoria) para um dossiê,
assina-os digitalmente (PAdES) e devolve os bytes. É um serviço interno (S2S): o
gateway o chama via HTTP e faz proxy do PDF ao cliente.

Fonte de dados: PostgreSQL (via core.db.repositories) — SEM Kafka. Diretório com
hífen ⇒ não é pacote; executa-se diretamente (`python services/report-service/app.py`),
o que coloca este diretório em sys.path e torna `schemas`/`generator`/`signer` importáveis.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Garante que os módulos irmãos (schemas/generator/signer) sejam importáveis tanto
# ao rodar como script quanto ao ser carregado via importlib nos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generator  # noqa: E402
import signer  # noqa: E402
import structlog  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, status  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from schemas import ReportMetadata, ReportRequest  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from core.db.engine import get_session  # noqa: E402
from core.db.repositories.dossie import DossieRecord, DossieRepository  # noqa: E402
from core.security.audit import get_audit_repo  # noqa: E402

logger = structlog.get_logger(__name__)

# Permite servir PDF não-assinado quando o PyHanko não está instalado (dev sem deps).
ALLOW_UNSIGNED = os.environ.get("REPORT_ALLOW_UNSIGNED", "0") == "1"

_LEGAL_REFERENCES = [
    ("LGPD – Art. 20", "Direito à revisão de decisões automatizadas que afetem interesses do titular."),
    ("LGPD – Art. 37", "Registro das operações de tratamento de dados pessoais (trilha de auditoria)."),
    ("Res. CMN 4.966/2021", "Provisionamento e classificação de risco de operações de crédito."),
    ("Res. Bacen 4.557/2017", "Estrutura de gerenciamento integrado de riscos e de capital."),
]

_AGENT_SECTIONS = (
    ("esg", "ESG / Socioambiental", "esg_rationale", "esg_score"),
    ("financial", "Financeiro", "financial_rationale", "financial_score"),
    ("security", "Segurança / Identidade", "security_rationale", "security_score"),
)


def _mask_hash(value: str) -> str:
    """Mascara o hash do CPF (nunca expõe o CPF; exibe só um prefixo curto)."""
    return f"{value[:8]}***" if value else "—"


def build_agent_sections(rationale: dict[str, Any], record: DossieRecord) -> list[dict[str, Any]]:
    """Normaliza o XAI consolidado em seções por agente para o template."""
    scores = {
        "esg_score": record.esg_score,
        "financial_score": record.financial_score,
        "security_score": record.security_score,
    }
    sections: list[dict[str, Any]] = []
    for key, title, rationale_key, score_key in _AGENT_SECTIONS:
        block = rationale.get(rationale_key, {}) or {}
        factors = block.get("factors", []) or []
        sections.append(
            {
                "key": key,
                "title": title,
                "score": scores[score_key],
                "decision": block.get("decision"),
                "confidence": block.get("confidence"),
                "factors": factors,
            }
        )
    return sections


def build_compliance_context(
    record: DossieRecord,
    audit_entries: list[dict[str, Any]],
    metadata: ReportMetadata,
) -> dict[str, Any]:
    """Monta o contexto do template de compliance a partir do dossiê e da auditoria."""
    rationale = record.xai_consolidated_rationale or {}
    return {
        "dossie": {
            "id": record.dossie_id,
            "tenant_id": record.tenant_id,
            "status": record.status,
            "verdict": record.verdict,
            "car_number": record.car_number,
            "cpf_hash_masked": _mask_hash(record.producer_cpf_hash),
            "credit_amount_brl": record.credit_amount_brl,
            "approved_amount_brl": record.approved_amount_brl,
            "credit_purpose": record.credit_purpose,
            "property_area_ha": record.property_area_ha,
            "requested_by": record.requested_by,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "rejection_reasons": record.rejection_reasons,
        },
        "scores": {
            "esg": record.esg_score,
            "financial": record.financial_score,
            "security": record.security_score,
            "composite": record.composite_score,
        },
        "agents": build_agent_sections(rationale, record),
        "audit": audit_entries,
        "legal_references": _LEGAL_REFERENCES,
        "meta": {
            "report_id": metadata.report_id,
            "generated_at": metadata.display_generated_at(),
            "generated_by": metadata.generated_by,
            "chain_head_hash": metadata.chain_head_hash,
            "audit_entries": metadata.audit_entries,
            "signed": metadata.signed,
            "signer_subject": metadata.signer_subject,
        },
    }


async def _fetch_audit_rows(dossie_id: str, tenant_id: str) -> list[dict[str, Any]]:
    entries = await get_audit_repo().get_by_resource(dossie_id)
    rows: list[dict[str, Any]] = []
    for e in entries:
        if e.tenant_id != tenant_id:
            continue
        rows.append(
            {
                "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
                "timestamp": e.timestamp,
                "subject": e.subject,
                "outcome": e.outcome,
                "entry_hash": e.entry_hash,
                "entry_hash_short": (e.entry_hash[:12] + "…") if e.entry_hash else "—",
                "details": e.details,
            }
        )
    return rows


def _render_and_sign(
    context: dict[str, Any], report_type: str, metadata: ReportMetadata
) -> tuple[bytes, ReportMetadata]:
    """Gera o PDF e o assina (ou o devolve sem assinatura, se permitido)."""
    if report_type == "audit":
        pdf = generator.generate_audit_pdf(context)
    else:
        pdf = generator.generate_compliance_pdf(context)

    if signer.is_signing_available():
        try:
            signed = signer.sign_pdf(pdf)
            metadata = metadata.model_copy(
                update={"signed": True, "signer_subject": signer.signer_subject_cn()}
            )
            return signed, metadata
        except Exception as exc:  # pragma: no cover - falha de assinatura em runtime
            logger.error("pdf_sign_failed", error=str(exc))
            if not ALLOW_UNSIGNED:
                raise
    elif not ALLOW_UNSIGNED:
        raise RuntimeError("Assinatura indisponível (PyHanko ausente) e REPORT_ALLOW_UNSIGNED != 1")

    logger.warning("pdf_unsigned", report_id=metadata.report_id)
    return pdf, metadata


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgroTrust AI – Report Service",
        description="Geração e assinatura de relatórios PDF de compliance e auditoria.",
        version="0.1.0",
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "agrotrust-report-service",
            "signing_available": signer.is_signing_available(),
        }

    @app.post("/reports/{dossie_id}", responses={200: {"content": {"application/pdf": {}}}})
    async def generate_report(
        dossie_id: str,
        body: ReportRequest,
        session: AsyncSession = Depends(get_session),
    ) -> StreamingResponse:
        from io import BytesIO

        record = await DossieRepository(session).get_by_id(dossie_id, body.tenant_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dossiê '{dossie_id}' não encontrado")

        audit_rows = await _fetch_audit_rows(dossie_id, body.tenant_id)
        head_hash = audit_rows[-1]["entry_hash"] if audit_rows else ""
        metadata = ReportMetadata(
            dossie_id=dossie_id,
            tenant_id=body.tenant_id,
            report_type=body.report_type,
            generated_by=body.requested_by,
            chain_head_hash=head_hash,
            audit_entries=len(audit_rows),
        )
        context = build_compliance_context(record, audit_rows, metadata)

        try:
            pdf_bytes, metadata = _render_and_sign(context, body.report_type, metadata)
        except Exception as exc:
            logger.error("report_generation_failed", dossie_id=dossie_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao gerar o relatório"
            ) from exc

        logger.info("report_generated", dossie_id=dossie_id, report_id=metadata.report_id, signed=metadata.signed)
        filename = f"agrotrust_{dossie_id}.pdf"
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Report-Id": metadata.report_id,
                "X-Report-Signed": str(metadata.signed).lower(),
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8020"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104
