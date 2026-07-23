# AgroTrust AI

SaaS agêntico de subscrição de crédito rural. Motor multiagente (ESG, Financeiro,
Segurança) orquestrado via LangGraph, com veredicto explicável (XAI), auditoria
imutável (hash chain) e persistência PostgreSQL.

## Stack

- **core/** – settings, security (JWT/IAM/audit/crypto), events (Kafka), db (asyncpg)
- **agents/** – ESG, Financial, Security, Orchestrator (VerdictEngine)
- **services/** – gateway (FastAPI), agent-runner (Kafka consumer), microsserviços de agente
- **mocks/** – APIs governamentais determinísticas (SICAR, GEE, Dataprev, Open Finance)

## Ambiente completo (um comando)

```bash
make stack-up      # infra (Kafka/PG/Redis) + mocks + aplicação
make migrate       # aplica core/db/migrations/001_initial.sql no PostgreSQL
```

Aplicação:

```bash
make app-build     # build das imagens da aplicação
make app-up        # sobe gateway + agent-runner + 3 microsserviços
make app-logs      # tail dos logs
make app-down      # derruba a aplicação
```

## Testes

```bash
make test          # suíte completa (pytest)
```

## Fases

- **Fase 1** – Núcleo agêntico, eventos, mocks, segurança.
- **Fase 2** – Persistência real (PostgreSQL asyncpg), projeções de leitura,
  API Gateway completo, Dockerfiles e docker-compose da aplicação.
