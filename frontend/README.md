# AgroTrust AI — Frontend (Fase 3)

SPA React 19 + Vite 5 + TypeScript + TailwindCSS + shadcn/ui + Recharts +
@tanstack/react-query + react-router. Consome o API Gateway (porta 8000).

## Rodando em desenvolvimento

```bash
# a partir da raiz do repositório
make frontend-dev          # npm install + vite dev-server em http://localhost:5173
# (o gateway precisa estar no ar em :8000 — `make app-up`)
```

O dev-server faz proxy de `/api` e `/token` para `http://localhost:8000`, então
não há CORS. Login de dev:

- `analista@agrotrust.ai` / `analista123` (read/write + audit)
- `gestor@agrotrust.ai` / `gestor123` (+ admin:params + audit:export)

## Build e testes

```bash
make frontend-build        # tsc --noEmit + vite build → dist/
make frontend-test         # Vitest (DossieTable, RiskParamsForm, XAIPanel, AuditTimeline)
```

## Decisões de projeto relevantes

- **JWT só em memória** (`AuthContext`) — nunca em localStorage/sessionStorage/cookie.
  Ao recarregar a página, a sessão é perdida e o usuário volta a `/login` (esperado em dev).
- **CPF nunca é transmitido**: o `NewDossieModal` converte o CPF em `SHA-3-256`
  localmente (`js-sha3`) e envia apenas o hash. A tabela exibe o hash truncado.
- **Verificação de hash da auditoria**: a Web Crypto API não implementa SHA-3, então
  usamos `js-sha3` (FIPS-202, idêntico ao `hashlib.sha3_256` do backend). O gateway
  envia a string `canonical` exata que foi hasheada (o JSON não preserva a repr de
  floats do Python, inviabilizando reconstrução byte-a-byte no browser); o cliente
  recomputa `sha3_256(canonical)` e compara com `entry_hash`.
- **Fetching sempre via react-query** — nenhum `useEffect` para fetch puro.
- **Sem `any` explícito** — campos desconhecidos usam `unknown`.
- **Atividade recente** no dashboard é derivada dos dossiês mais recentes (não há
  endpoint global de auditoria; apenas por dossiê).

## Produção (Docker)

`frontend/Dockerfile.frontend` faz build multi-stage (node:20-alpine → nginx:alpine).
O `nginx.conf` serve a SPA (fallback `try_files`), faz proxy de `/api` e `/token`
para o `gateway`, e aplica CSP (`default-src 'self'; frame-ancestors 'none'`).
Sobe junto com o stack via `docker/docker-compose.app.yml` (porta 5173).
