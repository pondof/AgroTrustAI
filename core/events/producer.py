"""
AgroTrust AI – Kafka Producer assíncrono.

Garantias:
  - acks=all (todas as réplicas confirmam antes de ack ao producer).
  - Retentativas automáticas com backoff exponencial (tenacity).
  - Cada mensagem inclui headers de rastreabilidade (correlation_id, schema_version).
  - Serialização JSON com validação Pydantic antes do envio.
  - Dead Letter Queue (DLQ) automática em falha permanente.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config.settings import get_settings
from core.events.schemas import BaseEvent

logger = structlog.get_logger(__name__)


class KafkaProducer:
    """
    Producer Kafka assíncrono com retry, DLQ e headers de rastreabilidade.
    Usa aiokafka sob o capô; substitua por confluent-kafka em alta carga.
    """

    def __init__(self) -> None:
        self._settings = get_settings().kafka
        self._producer: Any = None   # aiokafka.AIOKafkaProducer

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import]

            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                enable_idempotence=True,
                max_in_flight_requests_per_connection=1,
                compression_type="gzip",
            )
            await self._producer.start()
            logger.info("kafka_producer_started", servers=self._settings.bootstrap_servers)
        except ImportError:
            logger.warning("aiokafka_not_installed_using_noop_producer")
            self._producer = _NoopProducer()

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(
        self,
        topic: str,
        event: BaseEvent,
        partition_key: str | None = None,
    ) -> None:
        """
        Publica um evento Pydantic no tópico Kafka com retry exponencial.
        Falha permanente → envia para DLQ (topic + '.dlq').
        """
        payload = event.model_dump()
        headers = [
            ("correlation_id", event.correlation_id.encode()),
            ("schema_version", event.schema_version.encode()),
            ("event_type", event.event_type.encode()),  # type: ignore[attr-defined]
        ]
        key = partition_key.encode() if partition_key else None

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(Exception),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                reraise=True,
            ):
                with attempt:
                    await self._producer.send_and_wait(
                        topic, value=payload, key=key, headers=headers
                    )
                    logger.info(
                        "event_published",
                        topic=topic,
                        event_id=event.event_id,
                        correlation_id=event.correlation_id,
                    )
        except Exception as exc:
            dlq_topic = f"{topic}.dlq"
            logger.error(
                "event_publish_failed_sending_to_dlq",
                topic=topic,
                dlq_topic=dlq_topic,
                error=str(exc),
                event_id=event.event_id,
            )
            await self._producer.send_and_wait(
                dlq_topic,
                value={"original_payload": payload, "error": str(exc)},
                key=key,
            )
            raise


class _NoopProducer:
    """Implementação noop para ambiente sem Kafka (CI sem infraestrutura)."""

    async def send_and_wait(self, topic: str, **kwargs: Any) -> None:
        logging.getLogger(__name__).debug("noop_kafka_send topic=%s", topic)

    async def stop(self) -> None:
        pass


# ─── Singleton ────────────────────────────────────────────────────────────────

_producer: KafkaProducer | None = None


async def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer()
        await _producer.start()
    return _producer
