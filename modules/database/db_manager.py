#!/usr/bin/env python3
"""
Guardian Database - Pattern Learning & History
PromptOS Module

Stores guardian decisions and system metrics for pattern learning.
Uses PostgreSQL for structured data and Qdrant for similarity search.

Features:
- Decision history storage
- System metrics time series
- Pattern recognition via Qdrant vectors
- Trend analysis
- Anomaly detection suggestions
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum


try:
    import psycopg2

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False


try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class DecisionType(Enum):
    MONITOR = "monitor"
    HEAL_WINDOWS = "heal_windows"
    HEAL_WSL = "heal_wsl"
    SHRINK_WSL = "shrink_wsl"
    RECOMMEND_REBOOT = "recommend_reboot"
    NO_ACTION = "no_action"


@dataclass
class MetricRecord:
    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    wsl_memory_mb: Optional[float]
    processes: int
    decision: str
    decision_confidence: str


@dataclass
class DecisionRecord:
    timestamp: datetime
    cpu_before: float
    ram_before: float
    disk_before: float
    decision: str
    confidence: str
    reasoning: str
    actions_taken: List[str]
    outcome: Optional[str]
    cpu_after: Optional[float]
    ram_after: Optional[float]


class GuardianDB:
    def __init__(
        self,
        pg_config: Optional[dict] = None,
        qdrant_url: str = "http://localhost:6333",
    ):
        self.logger = self._setup_logging()
        self.pg_config = pg_config
        self.qdrant_url = qdrant_url
        self.pg_conn = None
        self.qdrant_client = None

        if pg_config and POSTGRES_AVAILABLE:
            self._init_postgres()

        if QDRANT_AVAILABLE:
            self._init_qdrant()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("GuardianDB")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _init_postgres(self):
        try:
            self.pg_conn = psycopg2.connect(**self.pg_config)
            self.pg_cursor = self.pg_conn.cursor()

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_decisions (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    cpu_before FLOAT,
                    ram_before FLOAT,
                    disk_before FLOAT,
                    decision VARCHAR(50),
                    confidence VARCHAR(20),
                    reasoning TEXT,
                    actions_taken JSONB,
                    outcome VARCHAR(50),
                    cpu_after FLOAT,
                    ram_after FLOAT
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_metrics (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    cpu_percent FLOAT,
                    ram_percent FLOAT,
                    disk_percent FLOAT,
                    wsl_memory_mb FLOAT,
                    processes INTEGER,
                    temperature FLOAT,
                    network_status VARCHAR(20)
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    event_type VARCHAR(50),
                    severity VARCHAR(20),
                    title TEXT,
                    message TEXT,
                    details JSONB,
                    resolved BOOLEAN DEFAULT FALSE
                )
            """)

            # New tables for leak detection, ports, patterns
            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_leak_detections (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    process_name VARCHAR(100),
                    pid INTEGER,
                    leak_type VARCHAR(20),
                    severity VARCHAR(20),
                    memory_mb FLOAT,
                    growth_rate FLOAT,
                    description TEXT,
                    recommendation TEXT,
                    resolved BOOLEAN DEFAULT FALSE
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_port_scans (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    source VARCHAR(20),
                    total_connections INTEGER,
                    listening_ports INTEGER,
                    established_connections INTEGER,
                    ollama_instances INTEGER,
                    suspicious JSONB
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_patterns (
                    id SERIAL PRIMARY KEY,
                    pattern_type VARCHAR(50),
                    trigger_conditions JSONB,
                    frequency INTEGER,
                    last_triggered TIMESTAMP,
                    ai_recommendation TEXT,
                    success_rate FLOAT
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_alerts (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    alert_level VARCHAR(20),
                    title TEXT,
                    message TEXT,
                    sent_to_telegram BOOLEAN DEFAULT FALSE,
                    acknowledged BOOLEAN DEFAULT FALSE
                )
            """)

            self.pg_cursor.execute("""
                CREATE TABLE IF NOT EXISTS guard_suggestions (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    category VARCHAR(50),
                    title TEXT,
                    description TEXT,
                    action_text TEXT,
                    potential_impact VARCHAR(20),
                    implemented BOOLEAN DEFAULT FALSE
                )
            """)

            self.pg_conn.commit()
            self.logger.info("PostgreSQL initialized")
        except Exception as e:
            self.logger.warning(f"PostgreSQL init failed: {e}")
            self.pg_conn = None

    def _init_qdrant(self):
        try:
            self.qdrant_client = QdrantClient(url=self.qdrant_url)

            self.qdrant_client.recreate_collection(
                collection_name="guardian_snapshots",
                vectors_config=VectorParams(size=10, distance=Distance.COSINE),
            )
            self.logger.info("Qdrant initialized")
        except Exception as e:
            self.logger.warning(f"Qdrant init failed: {e}")
            self.qdrant_client = None

    def save_decision(self, decision: Dict[str, Any]) -> bool:
        success = False

        if self.pg_conn:
            try:
                self.pg_cursor.execute(
                    """
                    INSERT INTO guard_decisions 
                    (timestamp, cpu_before, ram_before, disk_before, decision, 
                     confidence, reasoning, actions_taken, outcome, cpu_after, ram_after)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        decision.get("timestamp", datetime.now().isoformat()),
                        decision.get("metrics", {}).get("cpu"),
                        decision.get("metrics", {}).get("ram"),
                        decision.get("metrics", {}).get("disk"),
                        decision.get("decision"),
                        decision.get("confidence"),
                        decision.get("reasoning"),
                        json.dumps(decision.get("actions_taken", [])),
                        decision.get("outcome"),
                        decision.get("cpu_after"),
                        decision.get("ram_after"),
                    ),
                )
                self.pg_conn.commit()
                success = True
            except Exception as e:
                self.logger.error(f"Failed to save decision: {e}")

        return success

    def save_metrics(self, metrics: Dict[str, Any]) -> bool:
        success = False

        if self.pg_conn:
            try:
                self.pg_cursor.execute(
                    """
                    INSERT INTO guard_metrics
                    (timestamp, cpu_percent, ram_percent, disk_percent, wsl_memory_mb, processes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (
                        datetime.now().isoformat(),
                        metrics.get("cpu_percent"),
                        metrics.get("ram_percent"),
                        metrics.get("disk_percent"),
                        metrics.get("wsl_memory_mb"),
                        metrics.get("processes"),
                    ),
                )
                self.pg_conn.commit()
                success = True
            except Exception as e:
                self.logger.error(f"Failed to save metrics: {e}")

        if self.qdrant_client:
            try:
                vector = self._metrics_to_vector(metrics)
                self.qdrant_client.upsert(
                    collection_name="guardian_snapshots",
                    points=[
                        PointStruct(
                            id=int(datetime.now().timestamp()),
                            vector=vector,
                            payload=metrics,
                        )
                    ],
                )
            except Exception as e:
                self.logger.warning(f"Failed to save to Qdrant: {e}")

        return success

    def _metrics_to_vector(self, metrics: Dict[str, Any]) -> List[float]:
        return [
            metrics.get("cpu_percent", 0) / 100.0,
            metrics.get("ram_percent", 0) / 100.0,
            metrics.get("disk_percent", 0) / 100.0,
            min((metrics.get("wsl_memory_mb", 0) or 0) / 8000.0, 1.0),
            min((metrics.get("processes", 0) or 0) / 1000.0, 1.0),
            0,
            0,
            0,
            0,
            0,
        ]

    def find_similar_situations(
        self, current_metrics: Dict[str, Any], limit: int = 5
    ) -> List[Dict]:
        if not self.qdrant_client:
            return []

        try:
            vector = self._metrics_to_vector(current_metrics)
            results = self.qdrant_client.search(
                collection_name="guardian_snapshots", query_vector=vector, limit=limit
            )

            return [{"score": r.score, "payload": r.payload} for r in results]
        except Exception as e:
            self.logger.warning(f"Similarity search failed: {e}")
            return []

    def get_decision_history(self, days: int = 7, limit: int = 100) -> List[Dict]:
        if not self.pg_conn:
            return []

        try:
            self.pg_cursor.execute(
                """
                SELECT timestamp, cpu_before, ram_before, disk_before, 
                       decision, confidence, reasoning, actions_taken, outcome
                FROM guard_decisions
                WHERE timestamp > %s
                ORDER BY timestamp DESC
                LIMIT %s
            """,
                (datetime.now() - timedelta(days=days), limit),
            )

            rows = self.pg_cursor.fetchall()
            return [
                {
                    "timestamp": r[0].isoformat() if r[0] else None,
                    "cpu_before": r[1],
                    "ram_before": r[2],
                    "disk_before": r[3],
                    "decision": r[4],
                    "confidence": r[5],
                    "reasoning": r[6],
                    "actions_taken": r[7]
                    if isinstance(r[7], list)
                    else json.loads(r[7])
                    if r[7]
                    else [],
                    "outcome": r[8],
                }
                for r in rows
            ]
        except Exception as e:
            self.logger.error(f"Failed to get history: {e}")
            return []

    def get_trends(self, days: int = 7) -> Dict[str, Any]:
        if not self.pg_conn:
            return {}

        try:
            self.pg_cursor.execute(
                """
                SELECT 
                    AVG(cpu_percent) as avg_cpu,
                    AVG(ram_percent) as avg_ram,
                    AVG(disk_percent) as avg_disk,
                    COUNT(*) as total_decisions,
                    SUM(CASE WHEN decision = 'heal_windows' THEN 1 ELSE 0 END) as windows_heals,
                    SUM(CASE WHEN decision = 'heal_wsl' THEN 1 ELSE 0 END) as wsl_heals,
                    SUM(CASE WHEN decision = 'shrink_wsl' THEN 1 ELSE 0 END) as wsl_shrinks
                FROM guard_decisions
                WHERE timestamp > %s
            """,
                (datetime.now() - timedelta(days=days),),
            )

            row = self.pg_cursor.fetchone()
            if row:
                return {
                    "avg_cpu": row[0],
                    "avg_ram": row[1],
                    "avg_disk": row[2],
                    "total_decisions": row[3],
                    "windows_heals": row[4],
                    "wsl_heals": row[5],
                    "wsl_shrinks": row[6],
                }
        except Exception as e:
            self.logger.error(f"Failed to get trends: {e}")

        return {}

    def get_patterns(self) -> Dict[str, Any]:
        history = self.get_decision_history(days=30)

        if not history:
            return {"patterns": [], "recommendations": []}

        patterns = []
        recommendations = []

        ram_heals = sum(1 for h in history if h["decision"] == "heal_windows")
        if ram_heals > 10:
            patterns.append("Frequent Windows memory healing - possible memory leak")
            recommendations.append("Review running processes for memory leaks")

        wsl_heals = sum(1 for h in history if h["decision"] == "heal_wsl")
        if wsl_heals > 5:
            patterns.append("Frequent WSL healing - consider more RAM allocation")

        avg_ram = sum(h["ram_before"] for h in history) / len(history)
        if avg_ram > 80:
            patterns.append(f"High average RAM usage ({avg_ram:.1f}%)")
            recommendations.append("Consider upgrading RAM or closing applications")

        return {"patterns": patterns, "recommendations": recommendations}

    def close(self):
        if self.pg_conn:
            self.pg_conn.close()
            self.logger.info("PostgreSQL connection closed")


class InMemoryDB:
    """Simple in-memory storage when PostgreSQL/Qdrant unavailable."""

    def __init__(self):
        self.decisions: List[Dict] = []
        self.metrics: List[Dict] = []
        self.logger = logging.getLogger("GuardianDB-InMemory")

    def save_decision(self, decision: Dict) -> bool:
        self.decisions.append(
            {
                "timestamp": decision.get("timestamp", datetime.now().isoformat()),
                **decision,
            }
        )
        if len(self.decisions) > 1000:
            self.decisions = self.decisions[-1000:]
        return True

    def save_metrics(self, metrics: Dict) -> bool:
        self.metrics.append({"timestamp": datetime.now().isoformat(), **metrics})
        if len(self.metrics) > 10000:
            self.metrics = self.metrics[-1000:]
        return True

    def get_decision_history(self, days: int = 7, limit: int = 100) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)
        filtered = [
            d
            for d in self.decisions
            if datetime.fromisoformat(d.get("timestamp", "2000")) > cutoff
        ]
        return sorted(filtered, key=lambda x: x.get("timestamp", ""), reverse=True)[
            :limit
        ]

    def get_trends(self, days: int = 7) -> Dict[str, Any]:
        recent = self.get_decision_history(days)
        if not recent:
            return {}

        return {
            "total_decisions": len(recent),
            "avg_cpu": sum(d.get("metrics", {}).get("cpu", 0) for d in recent)
            / len(recent),
            "avg_ram": sum(d.get("metrics", {}).get("ram", 0) for d in recent)
            / len(recent),
            "avg_disk": sum(d.get("metrics", {}).get("disk", 0) for d in recent)
            / len(recent),
        }

    def get_patterns(self) -> Dict[str, Any]:
        return {"patterns": [], "recommendations": []}


def create_db(pg_config: Optional[dict] = None) -> GuardianDB:
    """Create database connection with fallback to in-memory."""
    if pg_config and POSTGRES_AVAILABLE:
        return GuardianDB(pg_config)
    return InMemoryDB()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Guardian Database")
    parser.add_argument("--history", action="store_true", help="Show decision history")
    parser.add_argument("--trends", action="store_true", help="Show trends")
    parser.add_argument("--patterns", action="store_true", help="Show patterns")

    args = parser.parse_args()

    db = create_db()

    if args.history:
        history = db.get_decision_history(days=7)
        print(f"Recent Decisions ({len(history)}):")
        for h in history[:10]:
            print(
                f"  {h.get('timestamp', 'N/A')}: {h.get('decision')} ({h.get('confidence')})"
            )
            print(f"    Reasoning: {h.get('reasoning', '')[:80]}")

    elif args.trends:
        trends = db.get_trends(days=30)
        print("Trends (30 days):")
        for k, v in trends.items():
            print(f"  {k}: {v}")

    elif args.patterns:
        patterns = db.get_patterns()
        print("Patterns:")
        for p in patterns.get("patterns", []):
            print(f"  - {p}")
        print("\nRecommendations:")
        for r in patterns.get("recommendations", []):
            print(f"  - {r}")

    else:
        print("Guardian Database Tool")
        print("Usage: python db_manager.py --history")
