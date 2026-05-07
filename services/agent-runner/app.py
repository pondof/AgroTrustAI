"""
AgroTrust AI – Agent Runner: entry-point do serviço Kafka.

Inicializa o producer, o repositório de auditoria e o SubscriptionConsumer,
depois entra no consume_loop até receber SIGTERM/SIGINT.

Execução (a partir da raiz do projeto):
    PYTHONPATH=. python services/agent-runner/app.py
    # Docker: WORKDIR /app, CMD ["python", "services/agent-runner/app.py"]
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import structlog

from core.events.producer import KafkaProducer
from core.security.audit import AuditRepository

# agent-runner usa hífen → importa consumer via importlib para evitar SyntaxError
_consumer_path = Path(__file__).parent / "consumer.py"
_spec = importlib.util.spec_from_file_location("agent_runner_consumer", _consumer_path)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["agent_runner_consumer"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
SubscriptionConsumer = _mod.SubscriptionConsumer

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("agent_runner_starting")

    producer = KafkaProducer()
    await producer.start()

    audit_repo = AuditRepository()

    consumer = SubscriptionConsumer(
        producer=producer,
        audit_repo=audit_repo,
    )
    await consumer.start()

    logger.info("agent_runner_ready")

    try:
        await consumer.consume_loop()
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("agent_runner_stopped")


if __name__ == "__main__":
    asyncio.run(main())
