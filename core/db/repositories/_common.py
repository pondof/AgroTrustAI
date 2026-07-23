"""
Helpers internos compartilhados pelos repositórios.

Objetivo: manter os repositórios portáveis entre PostgreSQL (asyncpg, produção)
e SQLite (aiosqlite, testes) sem ramificar a lógica de negócio.

  - Campos JSON/JSONB: bind via tipo genérico sqlalchemy.JSON (serializa por dialeto).
  - Arrays TEXT[] (rejection_reasons): ARRAY(Text) no PostgreSQL, JSON no SQLite.
  - Leitura defensiva: o driver pode retornar dict/list já parseados (asyncpg jsonb,
    text[]) ou strings JSON (sqlite) – as_dict/as_list normalizam ambos os casos.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, BindParameter, Text, bindparam
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

_POSTGRES = "postgresql"


def dialect_name(session: AsyncSession) -> str:
    """Nome do dialeto do bind da sessão (ex.: 'postgresql', 'sqlite')."""
    bind = session.get_bind()
    return bind.dialect.name


def json_param(name: str) -> BindParameter[Any]:
    """Bind param JSON portável (JSONB no PG, texto serializado no SQLite)."""
    return bindparam(name, type_=JSON())


def array_param(name: str, session: AsyncSession) -> BindParameter[Any]:
    """
    Bind param para colunas TEXT[]: ARRAY(Text) no PostgreSQL (envia lista nativa),
    JSON no SQLite (serializa a lista). Em ambos os casos o *valor* é uma list[str].
    """
    if dialect_name(session) == _POSTGRES:
        return bindparam(name, type_=ARRAY(Text()))
    return bindparam(name, type_=JSON())


def as_dict(value: Any) -> dict[str, Any]:
    """Normaliza um valor JSON(B) lido do banco para dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str | bytes):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def as_list(value: Any) -> list[str]:
    """Normaliza um valor TEXT[]/JSON lido do banco para list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str | bytes):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return [str(v) for v in parsed] if isinstance(parsed, list) else []
    return []
