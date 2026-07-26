"""
AgroTrust AI – report-service: geração de PDF (HTML→PDF via WeasyPrint + Jinja2).

Restrições de segurança:
  - A geração NUNCA busca recursos externos na rede (--disable-network equivalente):
    o url_fetcher só resolve `data:` URIs; qualquer http(s)/file externo é recusado.
  - Todo CSS/imagem deve estar inline ou como data-URI nos templates.

As dependências pesadas (WeasyPrint) são importadas de forma preguiçosa dentro das
funções, para que este módulo seja importável mesmo sem elas instaladas (ex.: CI que
só testa a camada de template).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"

COMPLIANCE_TEMPLATE = "compliance_report.html.j2"
AUDIT_TEMPLATE = "audit_report.html.j2"

_env: Environment | None = None


def _brl(value: Any) -> str:
    """Formata um número como moeda BRL (filtro Jinja)."""
    if value is None:
        return "—"
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)


def _score(value: Any) -> str:
    """Formata um score 0–1000 (inteiro) ou '—' se ausente."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.0f}"
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)


def get_environment() -> Environment:
    """Environment Jinja2 (singleton) com autoescape e filtros customizados."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        _env.filters["brl"] = _brl
        _env.filters["score"] = _score
        _env.filters["pct"] = _pct
    return _env


def render_html(template_name: str, context: dict[str, Any]) -> str:
    """Renderiza um template Jinja2 para string HTML."""
    template = get_environment().get_template(template_name)
    return template.render(**context)


def _no_network_url_fetcher(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    url_fetcher para WeasyPrint que bloqueia qualquer recurso externo: apenas
    `data:` URIs são resolvidos (delegados ao fetcher padrão). Impede SSRF e
    vazamento de dados na geração do PDF.
    """
    # Checagem de segurança ANTES de qualquer import pesado: recursos não-`data:`
    # são recusados independentemente de o WeasyPrint estar instalado.
    if not url.startswith("data:"):
        raise ValueError(f"Recurso externo bloqueado na geração do PDF: {url!r}")
    from weasyprint.urls import default_url_fetcher

    return default_url_fetcher(url, *args, **kwargs)


def html_to_pdf(html: str, base_url: str | None = None) -> bytes:
    """Converte HTML em bytes de PDF (WeasyPrint), com rede desabilitada."""
    from weasyprint import HTML  # import preguiçoso (dependência pesada)

    document = HTML(string=html, base_url=base_url, url_fetcher=_no_network_url_fetcher)
    pdf = document.write_pdf()
    assert pdf is not None  # write_pdf() sem target sempre retorna bytes
    return pdf


def generate_compliance_pdf(context: dict[str, Any]) -> bytes:
    """Gera o PDF do relatório de compliance (LGPD/Bacen) do dossiê."""
    html = render_html(COMPLIANCE_TEMPLATE, context)
    return html_to_pdf(html)


def generate_audit_pdf(context: dict[str, Any]) -> bytes:
    """Gera o PDF do relatório tabular da trilha de auditoria."""
    html = render_html(AUDIT_TEMPLATE, context)
    return html_to_pdf(html)
