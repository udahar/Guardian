#!/usr/bin/env python3
"""
Guardian Database Integration Tests
Tests PostgreSQL and Qdrant connections with actual database operations.
"""

import unittest
import os
import sys
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestPostgreSQLConnection(unittest.TestCase):
    """Test PostgreSQL connection and operations."""

    @classmethod
    def setUpClass(cls):
        """Check if PostgreSQL is available."""
        cls.pg_available = False
        try:
            import psycopg2
            from Guardian.config import GuardianSettings

            cls.psycopg2 = psycopg2
            # Use GuardianSettings config
            config = GuardianSettings()
            cls.pg_config = {
                "host": config.db_host,
                "port": config.db_port,
                "database": config.db_name,
                "user": config.db_user,
                "password": config.db_password,
            }
            # Test connection
            try:
                conn = psycopg2.connect(**cls.pg_config)
                conn.close()
                cls.pg_available = True
                print(f"PostgreSQL connected: {config.db_name}@{config.db_host}")
            except Exception as e:
                print(f"PostgreSQL not available: {e}")
        except ImportError:
            print("psycopg2 not installed")

    def test_psycopg2_import(self):
        """Verify psycopg2 is available."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not configured")
        import psycopg2

        self.assertIsNotNone(psycopg2)

    def test_postgres_connection(self):
        """Test actual PostgreSQL connection."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)
        self.assertIsNotNone(db.pg_conn)
        self.assertIsNotNone(db.pg_cursor)
        db.close()

    def test_guard_decisions_table_exists(self):
        """Verify guard_decisions table is created."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        db.pg_cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'guard_decisions'
        """)
        columns = {row[0]: row[1] for row in db.pg_cursor.fetchall()}

        self.assertIn("timestamp", columns)
        self.assertIn("cpu_before", columns)
        self.assertIn("decision", columns)
        self.assertIn("reasoning", columns)
        db.close()

    def test_guard_metrics_table_exists(self):
        """Verify guard_metrics table is created."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        db.pg_cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'guard_metrics'
        """)
        columns = {row[0] for row in db.pg_cursor.fetchall()}

        self.assertIn("cpu_percent", columns)
        self.assertIn("ram_percent", columns)
        self.assertIn("disk_percent", columns)
        db.close()

    def test_guard_events_table_exists(self):
        """Verify guard_events table is created."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        db.pg_cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'guard_events'
        """)
        columns = {row[0] for row in db.pg_cursor.fetchall()}

        self.assertIn("event_type", columns)
        self.assertIn("severity", columns)
        self.assertIn("resolved", columns)
        db.close()

    def test_save_decision(self):
        """Test saving a decision to PostgreSQL."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        decision = {
            "timestamp": datetime.now().isoformat(),
            "metrics": {"cpu": 50.0, "ram": 60.0, "disk": 70.0},
            "decision": "monitor",
            "confidence": "high",
            "reasoning": "Test decision",
            "actions_taken": ["check_system"],
            "outcome": "success",
            "cpu_after": 45.0,
            "ram_after": 55.0,
        }

        result = db.save_decision(decision)
        self.assertTrue(result)

        # Verify it was saved
        db.pg_cursor.execute("""
            SELECT decision, reasoning FROM guard_decisions 
            ORDER BY id DESC LIMIT 1
        """)
        row = db.pg_cursor.fetchone()
        self.assertEqual(row[0], "monitor")
        self.assertEqual(row[1], "Test decision")
        db.close()

    def test_save_metrics(self):
        """Test saving metrics to PostgreSQL."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        metrics = {
            "cpu_percent": 45.5,
            "ram_percent": 62.3,
            "disk_percent": 75.0,
            "wsl_memory_mb": 2048.0,
            "processes": 150,
        }

        result = db.save_metrics(metrics)
        self.assertTrue(result)

        # Verify
        db.pg_cursor.execute("""
            SELECT cpu_percent, ram_percent FROM guard_metrics 
            ORDER BY id DESC LIMIT 1
        """)
        row = db.pg_cursor.fetchone()
        self.assertAlmostEqual(row[0], 45.5, places=1)
        db.close()

    def test_get_decision_history(self):
        """Test retrieving decision history."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        # Insert test data
        db.pg_cursor.execute(
            """
            INSERT INTO guard_decisions 
            (timestamp, cpu_before, ram_before, decision, confidence, reasoning, actions_taken)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (
                datetime.now().isoformat(),
                50.0,
                60.0,
                "monitor",
                "high",
                "Test",
                '["test"]',
            ),
        )
        db.pg_conn.commit()

        history = db.get_decision_history(days=7, limit=10)
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0)

        # Verify structure
        first = history[0]
        self.assertIn("timestamp", first)
        self.assertIn("decision", first)
        self.assertIn("reasoning", first)
        db.close()

    def test_get_trends(self):
        """Test retrieving trends."""
        if not self.pg_available:
            self.skipTest("PostgreSQL not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(pg_config=self.pg_config)

        trends = db.get_trends(days=30)
        self.assertIsInstance(trends, dict)

        # Should have these keys if data exists
        if trends:
            self.assertIn("avg_cpu", trends)
            self.assertIn("total_decisions", trends)
        db.close()


class TestQdrantConnection(unittest.TestCase):
    """Test Qdrant vector database connection."""

    @classmethod
    def setUpClass(cls):
        """Check if Qdrant is available."""
        cls.qdrant_available = False
        try:
            from qdrant_client import QdrantClient
            from Guardian.config import GuardianSettings

            cls.qdrant_client = QdrantClient
            config = GuardianSettings()

            # Try to connect
            client = QdrantClient(url=config.qdrant_url)
            client.get_collections()
            cls.qdrant_available = True
            cls.client = client
            print(f"Qdrant connected: {config.qdrant_url}")
        except Exception as e:
            print(f"Qdrant not available: {e}")

    def test_qdrant_import(self):
        """Verify Qdrant client is available."""
        if not self.qdrant_available:
            self.skipTest("Qdrant not available")
        from qdrant_client import QdrantClient

        self.assertIsNotNone(QdrantClient)

    def test_qdrant_connection(self):
        """Test actual Qdrant connection."""
        if not self.qdrant_available:
            self.skipTest("Qdrant not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(qdrant_url="http://localhost:6333")
        self.assertIsNotNone(db.qdrant_client)
        db.close()

    def test_qdrant_collection_exists(self):
        """Verify guardian_snapshots collection exists."""
        if not self.qdrant_available:
            self.skipTest("Qdrant not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB(qdrant_url="http://localhost:6333")

        collections = db.qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]

        self.assertIn("guardian_snapshots", collection_names)
        db.close()

    def test_save_and_search_metrics(self):
        """Test saving metrics to Qdrant and searching."""
        if not self.qdrant_available:
            self.skipTest("Qdrant not available")

        from Guardian.db_manager import GuardianDB

        # Use the PostgreSQL config too
        db = GuardianDB(
            pg_config=TestPostgreSQLConnection.pg_config,
            qdrant_url="http://localhost:6333",
        )

        metrics = {
            "cpu_percent": 45.0,
            "ram_percent": 60.0,
            "disk_percent": 70.0,
            "wsl_memory_mb": 2048.0,
            "processes": 150,
        }

        # Save metrics
        result = db.save_metrics(metrics)
        self.assertTrue(result)

        # Search for similar situations
        similar = db.find_similar_situations(metrics, limit=5)
        self.assertIsInstance(similar, list)

        db.close()

    def test_metrics_to_vector(self):
        """Test vector conversion from metrics."""
        if not self.qdrant_available:
            self.skipTest("Qdrant not available")

        from Guardian.db_manager import GuardianDB

        db = GuardianDB()

        metrics = {
            "cpu_percent": 50.0,
            "ram_percent": 75.0,
            "disk_percent": 80.0,
            "wsl_memory_mb": 4096.0,
            "processes": 200,
        }

        vector = db._metrics_to_vector(metrics)

        self.assertEqual(len(vector), 10)
        self.assertAlmostEqual(vector[0], 0.5)  # cpu/100
        self.assertAlmostEqual(vector[1], 0.75)  # ram/100
        self.assertAlmostEqual(vector[2], 0.8)  # disk/100


class TestInMemoryFallback(unittest.TestCase):
    """Test in-memory database fallback."""

    def test_in_memory_creation(self):
        """Test creating in-memory database."""
        from Guardian.db_manager import InMemoryDB

        db = InMemoryDB()
        self.assertIsNotNone(db)
        self.assertEqual(len(db.decisions), 0)
        self.assertEqual(len(db.metrics), 0)

    def test_save_decision_in_memory(self):
        """Test saving decision to in-memory DB."""
        from Guardian.db_manager import InMemoryDB

        db = InMemoryDB()

        decision = {
            "timestamp": datetime.now().isoformat(),
            "decision": "monitor",
            "confidence": "high",
            "reasoning": "Test",
        }

        result = db.save_decision(decision)
        self.assertTrue(result)
        self.assertEqual(len(db.decisions), 1)

    def test_save_metrics_in_memory(self):
        """Test saving metrics to in-memory DB."""
        from Guardian.db_manager import InMemoryDB

        db = InMemoryDB()

        metrics = {
            "cpu_percent": 50.0,
            "ram_percent": 60.0,
            "disk_percent": 70.0,
        }

        result = db.save_metrics(metrics)
        self.assertTrue(result)
        self.assertEqual(len(db.metrics), 1)

    def test_get_history_in_memory(self):
        """Test retrieving history from in-memory DB."""
        from Guardian.db_manager import InMemoryDB

        db = InMemoryDB()

        # Add some decisions
        for i in range(5):
            db.save_decision(
                {
                    "timestamp": datetime.now().isoformat(),
                    "decision": "monitor",
                }
            )

        history = db.get_decision_history(days=7, limit=10)
        self.assertEqual(len(history), 5)

    def test_in_memory_limit(self):
        """Test in-memory DB respects limits."""
        from Guardian.db_manager import InMemoryDB

        db = InMemoryDB()

        # Add more than limit
        for i in range(1500):
            db.save_decision({"timestamp": datetime.now().isoformat()})

        # Should be capped at 1000
        self.assertLessEqual(len(db.decisions), 1000)


class TestCreateDBFactory(unittest.TestCase):
    """Test the create_db factory function."""

    def test_create_db_with_config(self):
        """Test create_db with PostgreSQL config."""
        from Guardian.db_manager import create_db, InMemoryDB

        # With no config, should return InMemoryDB
        db = create_db()
        self.assertIsInstance(db, InMemoryDB)

    @patch("Guardian.db_manager.POSTGRES_AVAILABLE", False)
    def test_create_db_fallback(self):
        """Test fallback to in-memory when PostgreSQL unavailable."""
        from Guardian.db_manager import create_db, InMemoryDB

        db = create_db(pg_config={"host": "localhost"})
        self.assertIsInstance(db, InMemoryDB)


if __name__ == "__main__":
    unittest.main(verbosity=2)
