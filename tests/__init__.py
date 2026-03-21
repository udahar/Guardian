#!/usr/bin/env python3
"""
Guardian Test Suite
"""

import unittest
import os
import sys
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path (so "Guardian." imports work)
test_dir = os.path.dirname(os.path.abspath(__file__))
guardian_dir = os.path.dirname(test_dir)
parent_dir = os.path.dirname(guardian_dir)

sys.path.insert(0, parent_dir)
sys.path.insert(0, guardian_dir)


class TestConfigValidation(unittest.TestCase):
    """Test configuration validation."""

    def test_default_config_valid(self):
        """Test that default configuration is valid."""
        from Guardian.config import GuardianSettings

        config = GuardianSettings()
        errors = config.validate()
        self.assertEqual(len(errors), 0)

    def test_invalid_wsl_distro(self):
        """Test that invalid WSL distro names are rejected."""
        from Guardian.config import GuardianSettings

        config = GuardianSettings(wsl_distro="../../etc/passwd")
        errors = config.validate()
        self.assertTrue(any("Invalid WSL distro" in e for e in errors))

    def test_invalid_interval(self):
        """Test that invalid intervals are rejected."""
        from Guardian.config import GuardianSettings

        config = GuardianSettings(check_interval=5)
        errors = config.validate()
        self.assertTrue(any("check_interval" in e for e in errors))

    def test_dry_run_mode(self):
        """Test that dry run mode is configurable."""
        from Guardian.config import GuardianSettings

        config = GuardianSettings(dry_run=True)
        self.assertTrue(config.dry_run)

    def test_safe_targets(self):
        """Test cleanup target safety checks."""
        from Guardian.config import GuardianSettings

        config = GuardianSettings()
        self.assertTrue(config.is_safe_target("temp"))
        self.assertFalse(config.is_safe_target("windows_update"))

    def test_env_loading(self):
        """Test loading from environment variables."""
        os.environ["GUARDIAN_WSL_DISTRO"] = "Debian"
        os.environ["GUARDIAN_CHECK_INTERVAL"] = "120"

        from Guardian.config import load_config_from_env

        config = load_config_from_env()

        self.assertEqual(config.wsl_distro, "Debian")
        self.assertEqual(config.check_interval, 120)

        # Cleanup
        del os.environ["GUARDIAN_WSL_DISTRO"]
        del os.environ["GUARDIAN_CHECK_INTERVAL"]


class TestInputValidation(unittest.TestCase):
    """Test input validation functions."""

    def test_validate_command_input(self):
        """Test command input validation."""
        from Guardian.config import validate_command_input

        # Valid inputs
        self.assertTrue(validate_command_input("Ubuntu"))
        self.assertTrue(validate_command_input("Debian-22"))
        self.assertTrue(validate_command_input("my_distro"))

        # Invalid inputs
        self.assertFalse(validate_command_input("../../../etc"))
        self.assertFalse(validate_command_input("; rm -rf /"))
        self.assertFalse(validate_command_input("$(whoami)"))

    def test_sanitize_path(self):
        """Test path sanitization."""
        from Guardian.config import sanitize_path

        result = sanitize_path("test/path")
        self.assertTrue(isinstance(result, str))
        self.assertTrue(len(result) > 0)


class TestHeartbeatLogger(unittest.TestCase):
    """Test heartbeat logging."""

    @patch("os.makedirs")
    def test_logger_initialization(self, mock_makedirs):
        """Test logger initializes correctly."""
        from Guardian.heartbeat_logger import HeartbeatLogger
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = HeartbeatLogger(log_dir=tmpdir)
            self.assertEqual(logger.log_dir, tmpdir)

    def test_heartbeat_entry(self):
        """Test heartbeat entry creation."""
        from Guardian.heartbeat_logger import HeartbeatLogger
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = HeartbeatLogger(log_dir=tmpdir)

            # This should not raise
            try:
                logger.heartbeat(
                    cpu=50.0,
                    ram=60.0,
                    disk=70.0,
                    wsl_running=True,
                    wsl_memory=2048.0,
                    network_healthy=True,
                    active_distros=["Ubuntu"],
                    issues=[],
                    actions=["test_action"],
                )
            except Exception as e:
                self.fail(f"Heartbeat raised exception: {e}")


class TestWindowsSensors(unittest.TestCase):
    """Test Windows sensors with mocking."""

    @patch("Guardian.windows_sensors.psutil")
    def test_get_cpu_percent(self, mock_psutil):
        """Test CPU percentage reading."""
        mock_psutil.cpu_percent.return_value = 50.0

        from Guardian.windows_sensors import WindowsSensors

        sensors = WindowsSensors()

        # This will use mock
        result = sensors.take_snapshot()
        self.assertIsNotNone(result)


class TestNetworkMonitor(unittest.TestCase):
    """Test network monitoring."""

    @patch("subprocess.run")
    def test_ping_check(self, mock_run):
        """Test ping functionality."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        from Guardian.network_monitor import NetworkMonitor

        monitor = NetworkMonitor()

        result = monitor.check_internet()
        self.assertTrue(result)


class TestWSLUtils(unittest.TestCase):
    """Test WSL utilities."""

    def test_shrink_result_dataclass(self):
        """Test ShrinkResult dataclass."""
        from Guardian.wsl_utils import ShrinkResult

        result = ShrinkResult(
            success=True, original_size_gb=50.0, new_size_gb=30.0, space_saved_gb=20.0
        )

        self.assertTrue(result.success)
        self.assertEqual(result.space_saved_gb, 20.0)


class TestAIGuardian(unittest.TestCase):
    """Test AI Guardian."""

    def test_decision_types(self):
        """Test decision type enum."""
        from Guardian.ai_guardian import DecisionType

        self.assertEqual(DecisionType.MONITOR.value, "monitor")
        self.assertEqual(DecisionType.HEAL_WINDOWS.value, "heal_windows")
        self.assertEqual(DecisionType.SHRINK_WSL.value, "shrink_wsl")

    @patch("requests.get")
    def test_ollama_check(self, mock_get):
        """Test Ollama availability check."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        from Guardian.ai_guardian import AIGuardianBrain

        brain = AIGuardianBrain()

        # Should not raise
        result = brain.is_ollama_available()
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
