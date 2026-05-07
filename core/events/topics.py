"""
AgroTrust AI – Definição e criação de tópicos Kafka.

Execute:  python -m core.events.topics create
"""
from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class TopicConfig:
    name: str
    partitions: int
    replication_factor: int
    retention_ms: int   # -1 = infinito


TOPICS: list[TopicConfig] = [
    # Fluxo principal de subscrição
    TopicConfig("agrotrust.subscription.initiated",   partitions=12, replication_factor=1, retention_ms=7 * 86400 * 1000),
    TopicConfig("agrotrust.agent.esg.result",         partitions=12, replication_factor=1, retention_ms=7 * 86400 * 1000),
    TopicConfig("agrotrust.agent.financial.result",   partitions=12, replication_factor=1, retention_ms=7 * 86400 * 1000),
    TopicConfig("agrotrust.agent.security.result",    partitions=12, replication_factor=1, retention_ms=7 * 86400 * 1000),
    TopicConfig("agrotrust.subscription.verdict",     partitions=12, replication_factor=1, retention_ms=365 * 86400 * 1000),

    # Dead Letter Queues (retentação longa para replay manual)
    TopicConfig("agrotrust.subscription.initiated.dlq",  partitions=3, replication_factor=1, retention_ms=-1),
    TopicConfig("agrotrust.agent.esg.result.dlq",        partitions=3, replication_factor=1, retention_ms=-1),
    TopicConfig("agrotrust.agent.financial.result.dlq",  partitions=3, replication_factor=1, retention_ms=-1),
    TopicConfig("agrotrust.agent.security.result.dlq",   partitions=3, replication_factor=1, retention_ms=-1),

    # Auditoria (compacted – retentação eterna)
    TopicConfig("agrotrust.audit.log",                partitions=6, replication_factor=1, retention_ms=-1),
]

TOPIC_NAMES = {t.name for t in TOPICS}


def create_topics(bootstrap_servers: str = "localhost:9092") -> None:
    """Cria os tópicos no Kafka se ainda não existirem."""
    try:
        from kafka.admin import KafkaAdminClient, NewTopic  # type: ignore[import]
        from kafka.errors import TopicAlreadyExistsError     # type: ignore[import]
    except ImportError:
        print("[WARN] kafka-python não instalado – pulando criação de tópicos.")
        return

    admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
    new_topics = [
        NewTopic(
            name=t.name,
            num_partitions=t.partitions,
            replication_factor=t.replication_factor,
            topic_configs={"retention.ms": str(t.retention_ms)},
        )
        for t in TOPICS
    ]
    try:
        admin.create_topics(new_topics=new_topics, validate_only=False)
        print(f"✅ {len(new_topics)} tópicos criados.")
    except TopicAlreadyExistsError:
        print("ℹ️  Tópicos já existem.")
    finally:
        admin.close()


if __name__ == "__main__":
    from core.config.settings import get_settings
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "create":
        create_topics(get_settings().kafka.bootstrap_servers)
    elif cmd == "list":
        for t in TOPICS:
            print(f"  {t.name:55s} partitions={t.partitions} replication={t.replication_factor}")
    else:
        print("Uso: python -m core.events.topics [create|list]")
