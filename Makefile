.PHONY: help install dev test lint type-check security-scan mocks-up mocks-down infra-up infra-down \
        app-build app-up app-down app-logs migrate stack-up stack-down

PYTHON := python3.11
PIP    := pip install --break-system-packages

help:
	@echo "AgroTrust AI – Comandos disponíveis:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Instala todas as dependências
	$(PIP) -e ".[core,ml,dev]"
	pre-commit install

lint: ## Roda ruff (linter + formatter)
	ruff check . --fix
	ruff format .

type-check: ## Roda mypy
	mypy core/ mocks/ --ignore-missing-imports

test: ## Roda suite de testes completa
	pytest tests/ -v --tb=short

test-unit: ## Apenas testes unitários
	pytest tests/unit/ -v

test-integration: ## Testes de integração (requer infra up)
	pytest tests/integration/ -v

security-scan: ## SAST com semgrep
	semgrep --config=auto core/ mocks/ services/

mocks-up: ## Sobe todos os mocks de APIs governamentais
	docker compose -f docker/docker-compose.mocks.yml up -d
	@echo "Mocks disponíveis:"
	@echo "  CAR/SICAR:    http://localhost:8001"
	@echo "  Google Earth: http://localhost:8002"
	@echo "  Dataprev/DaaS:http://localhost:8003"
	@echo "  Open Finance: http://localhost:8004"

mocks-down: ## Derruba mocks
	docker-compose -f docker/docker-compose.mocks.yml down

infra-up: ## Sobe infraestrutura completa (Kafka, Zookeeper, Redis, PG)
	docker-compose -f docker/docker-compose.yml up -d
	@echo "Aguardando Kafka ficar pronto..."
	@sleep 10
	$(PYTHON) -m core.events.topics create

infra-down: ## Derruba infraestrutura
	docker-compose -f docker/docker-compose.yml down -v

dev: infra-up mocks-up ## Ambiente de desenvolvimento completo
	@echo "✅ Ambiente de desenvolvimento pronto!"

logs: ## Tails dos logs de todos os serviços
	docker compose -f docker/docker-compose.yml logs -f

kafka-topics: ## Lista tópicos Kafka
	docker exec agrotrust-kafka kafka-topics.sh --list --bootstrap-server localhost:9092

app-build: ## Build das imagens da aplicação (gateway + agentes)
	docker compose -f docker/docker-compose.app.yml build

app-up: ## Sobe a stack de aplicação (requer infra + mocks no ar)
	docker compose -f docker/docker-compose.app.yml up -d
	@echo "Aplicação disponível:"
	@echo "  Gateway:          http://localhost:8000  (docs em /docs)"
	@echo "  Agent ESG:        http://localhost:8010"
	@echo "  Agent Financeiro: http://localhost:8011"
	@echo "  Agent Segurança:  http://localhost:8012"

app-down: ## Derruba a stack de aplicação
	docker compose -f docker/docker-compose.app.yml down

app-logs: ## Tail dos logs da aplicação
	docker compose -f docker/docker-compose.app.yml logs -f

migrate: ## Aplica a migração 001 no PostgreSQL da infra
	docker cp core/db/migrations/001_initial.sql agrotrust-postgres:/tmp/001_initial.sql
	docker exec agrotrust-postgres psql -U agrotrust -d agrotrust -f /tmp/001_initial.sql

stack-up: infra-up mocks-up app-build app-up ## Ambiente completo (infra + mocks + aplicação) com um comando
	@echo "Aguardando PostgreSQL..." && sleep 5
	@$(MAKE) migrate
	@echo "✅ Stack completo no ar. Rode 'make app-logs' para acompanhar."

stack-down: app-down mocks-down infra-down ## Derruba o stack completo
	@echo "Stack derrubado."

clean: ## Limpa artefatos de build e cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
