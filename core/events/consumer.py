"""
AgroTrust AI – Kafka Consumer assíncrono.

Garantias:
  - Validação Pydantic estrita via TOPIC_SCHEMAS antes de entregar ao handler.
  - Commit manual de offset (enable.auto.commit=False) somente após handle() OK.
  - Dead Letter Queue automática após N tentativas consecutivas.
  - Graceful shutdown com signal handlers SIGTERM/SIGINT.
  - structlog com correlation_id em todo log do ciclo de vida.
"""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import signal
from typing import Any

import structlog

from core.config.settings import get_settings
from core.events.schemas import BaseEvent
from core.events.topics import TOPIC_NAMES

try:
    from core.events.schemas import TOPIC_SCHEMAS
except ImportError:  # pragma: no cover – defensivo
    TOPIC_SCHEMAS = {}  # type: ignore[assignment]

logger = structlog.get_logger(__name__)

DEFAULT_MAX_RETRIES: int = 3


class _NoopConsumer:
    """Implementação noop para CI sem Kafka."""

    def __init__(self) -> None:
        self._closed = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self._closed = True

    async def commit(self) -> None:
        pass

    async def getmany(self, *_: Any, **__: Any) -> dict[Any, list[Any]]:
        await asyncio.sleep(0.05)
        return {}

    async def send_and_wait(self, topic: str, **kwargs: Any) -> None:
        logging.getLogger(__name__).debug("noop_kafka_send topic=%s", topic)


class BaseConsumer(abc.ABC):
    """
    Classe base abstrata. Subclasses implementam `handle(event)`.

    Uso:
        class ESGResultConsumer(BaseConsumer):
            async def handle(self, event: BaseEvent) -> None:
                ...

        consumer = await get_consumer(["agrotrust.agent.esg.result"], "esg-orchestrator")
        await consumer.consume_loop()
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._settings = get_settings().kafka
        self._topics = topics
        self._group_id = group_id
        self._max_retries = max_retries
        self._consumer: Any = _NoopConsumer()
        self._dlq_producer: Any = _NoopConsumer()
        self._stop_event = asyncio.Event()
        self._signal_handlers_installed = False

        unknown = [t for t in topics if t not in TOPIC_NAMES]
        if unknown:
            logger.warning("consumer_unknown_topics", topics=unknown)

    @abc.abstractmethod
    async def handle(self, event: BaseEvent) -> None:
        """Processa um evento já validado pelo schema do tópico."""

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore[import]

            self._consumer = AIOKafkaConsumer(
                *self._topics,
                bootstrap_servers=self._settings.bootstrap_servers,
                group_id=self._group_id,
                enable_auto_commit=False,
                auto_offset_reset=self._settings.auto_offset_reset,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                key_deserializer=lambda b: b.decode("utf-8") if b else None,
            )
            self._dlq_producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                enable_idempotence=True,
                compression_type="gzip",
            )
            await self._consumer.start()
            await self._dlq_producer.start()
            logger.info(
                "kafka_consumer_started",
                topics=self._topics,
                group_id=self._group_id,
            )
        except ImportError:
            logger.warning("aiokafka_not_installed_using_noop_consumer")

    async def stop(self) -> None:
        self._stop_event.set()
        try:
            await self._consumer.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("kafka_consumer_stop_error", error=str(exc))
        try:
            await self._dlq_producer.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("kafka_dlq_producer_stop_error", error=str(exc))
        logger.info("kafka_consumer_stopped", group_id=self._group_id)

    def _install_signal_handlers(self) -> None:
        if self._signal_handlers_installed:
            return
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._stop_event.set)
            self._signal_handlers_installed = True
        except (NotImplementedError, RuntimeError):
            # Windows ou contexto sem loop suporta apenas signal.signal
            logger.debug("signal_handlers_unavailable")

    async def _send_to_dlq(
        self,
        topic: str,
        payload: dict[str, Any],
        error: str,
        correlation_id: str | None,
    ) -> None:
        dlq_topic = f"{topic}.dlq"
        try:
            await self._dlq_producer.send_and_wait(
                dlq_topic,
                value={
                    "original_payload": payload,
                    "error": error,
                    "source_topic": topic,
                    "correlation_id": correlation_id,
                },
            )
            logger.error(
                "event_sent_to_dlq",
                dlq_topic=dlq_topic,
                error=error,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # pragma: no cover
            logger.critical(
                "dlq_publish_failed",
                dlq_topic=dlq_topic,
                error=str(exc),
                correlation_id=correlation_id,
            )

    def _validate(self, topic: str, raw: dict[str, Any]) -> BaseEvent:
        """Valida payload contra o schema do tópico ou levanta ValueError."""
        schema_cls = TOPIC_SCHEMAS.get(topic)
        if schema_cls is None:
            raise ValueError(f"Tópico '{topic}' sem schema registrado em TOPIC_SCHEMAS")
        return schema_cls.model_validate(raw)

    async def _process_record(self, topic: str, value: dict[str, Any]) -> None:
        correlation_id = value.get("correlation_id") if isinstance(value, dict) else None
        log = logger.bind(
            topic=topic,
            group_id=self._group_id,
            correlation_id=correlation_id,
        )
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                event = self._validate(topic, value)
                await self.handle(event)
                log.info("event_processed", attempt=attempt)
                return
            except Exception as exc:
                last_error = exc
                log.warning(
                    "event_processing_failed",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                # backoff progressivo (sem dependência externa)
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 10))

        await self._send_to_dlq(
            topic=topic,
            payload=value,
            error=f"{type(last_error).__name__}: {last_error}",
            correlation_id=correlation_id,
        )

    async def consume_loop(self) -> None:
        """Loop principal. Roda até receber SIGTERM/SIGINT ou stop()."""
        self._install_signal_handlers()
        log = logger.bind(group_id=self._group_id, topics=self._topics)
        log.info("consume_loop_started")

        try:
            while not self._stop_event.is_set():
                batches = await self._consumer.getmany(timeout_ms=1000)
                if not batches:
                    continue

                for tp, msgs in batches.items():
                    topic = getattr(tp, "topic", str(tp))
                    for msg in msgs:
                        if self._stop_event.is_set():
                            break
                        await self._process_record(topic=topic, value=msg.value)
                    # commit explícito após processar todas as mensagens da partição
                    try:
                        await self._consumer.commit()
                    except Exception as exc:  # pragma: no cover
                        log.error("offset_commit_failed", error=str(exc))
        except asyncio.CancelledError:
            log.info("consume_loop_cancelled")
            raise
        finally:
            log.info("consume_loop_exiting")


# ─── Singleton helper ────────────────────────────────────────────────────────


_consumers: dict[str, BaseConsumer] = {}


async def get_consumer(
    consumer_cls: type[BaseConsumer],
    topics: list[str],
    group_id: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> BaseConsumer:
    """
    Retorna instância singleton por group_id (idempotente para reinicialização).
    """
    key = f"{group_id}:{','.join(sorted(topics))}"
    if key not in _consumers:
        instance = consumer_cls(topics=topics, group_id=group_id, max_retries=max_retries)
        await instance.start()
        _consumers[key] = instance
    return _consumers[key]
