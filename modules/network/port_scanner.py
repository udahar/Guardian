#!/usr/bin/env python3
"""
Network Port Scanner - Windows & WSL Port Analysis
PromptOS Module

Scans and monitors open ports on Windows and WSL:
- Active connections (ESTABLISHED, LISTENING, etc.)
- Process owning each port
- Suspicious port detection
- Network leak/inappropriate connection detection

Features:
- Windows netstat parsing
- WSL netstat parsing
- Process binding detection
- Suspicious pattern alerts
"""

import subprocess
import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


class ConnectionState(Enum):
    LISTENING = "LISTENING"
    ESTABLISHED = "ESTABLISHED"
    TIME_WAIT = "TIME_WAIT"
    CLOSE_WAIT = "CLOSE_WAIT"
    SYN_SENT = "SYN_SENT"
    SYN_RECV = "SYN_RECV"
    FIN_WAIT = "FIN_WAIT"
    LAST_ACK = "LAST_ACK"
    CLOSING = "CLOSING"
    UNKNOWN = "UNKNOWN"


@dataclass
class PortConnection:
    protocol: str
    local_address: str
    local_port: int
    foreign_address: str
    foreign_port: int
    state: ConnectionState
    process_name: Optional[str]
    process_pid: Optional[int]


@dataclass
class PortScanResult:
    timestamp: datetime
    total_connections: int
    listening_ports: int
    established_connections: int
    connections: List[PortConnection] = field(default_factory=list)
    suspicious: List[str] = field(default_factory=list)
    ollama_ports: List[int] = field(default_factory=list)


class PortScanner:
    def __init__(self, wsl_distro: str = "Ubuntu"):
        self.wsl_distro = wsl_distro
        self.logger = self._setup_logging()

        # Known suspicious ports
        self.suspicious_ports = {
            23: "Telnet (unencrypted)",
            135: "Windows RPC",
            139: "NetBIOS",
            445: "SMB",
            1433: "MSSQL",
            3306: "MySQL",
            5432: "PostgreSQL",
            6379: "Redis",
            8080: "HTTP Proxy",
            8443: "HTTPS Alt",
            27017: "MongoDB",
        }

        # Known application ports
        self.app_ports = {
            11434: "Ollama",
            3000: "Node/Dev",
            5000: "Flask/API",
            8000: "HTTP Server",
            8888: "Jupyter",
            11434: "Ollama",
        }

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("PortScanner")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _parse_state(self, state_str: str) -> ConnectionState:
        state_str = state_str.upper().strip()
        try:
            return ConnectionState(state_str)
        except ValueError:
            return ConnectionState.UNKNOWN

    def _run_command(self, cmd: list, timeout: int = 15) -> str:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout
        except Exception as e:
            self.logger.error(f"Command failed: {e}")
            return ""

    def scan_windows(self) -> PortScanResult:
        """Scan Windows ports using netstat."""
        output = self._run_command(["netstat", "-ano"])

        connections = []
        listening = 0
        established = 0
        suspicious = []
        ollama_ports = []

        lines = output.split("\n")[4:]  # Skip headers

        for line in lines:
            line = line.strip()
            if not line or "Proto" in line:
                continue

            try:
                parts = line.split()
                if len(parts) < 4:
                    continue

                protocol = parts[0].lower()
                local = parts[1]
                foreign = parts[2]
                state = parts[3] if len(parts) > 3 else "UNKNOWN"

                # Parse local address
                if ":" in local:
                    local_addr, local_port = local.rsplit(":", 1)
                    local_port = int(local_port)
                else:
                    local_addr = local
                    local_port = 0

                # Parse foreign address
                if ":" in foreign:
                    foreign_addr, foreign_port = foreign.rsplit(":", 1)
                    try:
                        foreign_port = int(foreign_port)
                    except ValueError:
                        foreign_port = 0
                else:
                    foreign_addr = foreign
                    foreign_port = 0

                # Get PID and process name
                pid = None
                process_name = None
                if len(parts) > 4:
                    try:
                        pid = int(parts[-1])
                        if pid > 0:
                            try:
                                proc_result = subprocess.run(
                                    [
                                        "tasklist",
                                        "/FI",
                                        f"PID eq {pid}",
                                        "/FO",
                                        "CSV",
                                        "/NH",
                                    ],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                )
                                if proc_result.stdout.strip():
                                    process_name = (
                                        proc_result.stdout.strip()
                                        .split(",")[0]
                                        .strip('"')
                                    )
                            except Exception:
                                pass
                    except ValueError:
                        pass

                conn = PortConnection(
                    protocol=protocol,
                    local_address=local_addr,
                    local_port=local_port,
                    foreign_address=foreign_addr,
                    foreign_port=foreign_port,
                    state=self._parse_state(state),
                    process_name=process_name,
                    process_pid=pid,
                )
                connections.append(conn)

                if conn.state == ConnectionState.LISTENING:
                    listening += 1

                    # Check for suspicious
                    if local_port in self.suspicious_ports:
                        suspicious.append(
                            f"Port {local_port}: {self.suspicious_ports[local_port]} ({process_name})"
                        )

                    # Track Ollama
                    if local_port == 11434:
                        ollama_ports.append(11434)

                elif conn.state == ConnectionState.ESTABLISHED:
                    established += 1

                    # Check for suspicious foreign addresses
                    if (
                        foreign_addr
                        and not foreign_addr.startswith("127.")
                        and not foreign_addr.startswith("192.168.")
                        and not foreign_addr.startswith("10.")
                    ):
                        suspicious.append(
                            f"External connection: {foreign_addr}:{foreign_port} -> {process_name or pid}"
                        )

                    if local_port == 11434:
                        ollama_ports.append(11434)

            except Exception as e:
                self.logger.debug(f"Parse error: {e}")

        return PortScanResult(
            timestamp=datetime.now(),
            total_connections=len(connections),
            listening_ports=listening,
            established_connections=established,
            connections=connections,
            suspicious=suspicious,
            ollama_ports=list(set(ollama_ports)),
        )

    def scan_wsl(self) -> PortScanResult:
        """Scan WSL ports."""
        try:
            output = subprocess.run(
                ["wsl", "-d", self.wsl_distro, "netstat", "-tulpn"],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout
        except Exception as e:
            self.logger.error(f"WSL scan failed: {e}")
            return PortScanResult(
                timestamp=datetime.now(),
                total_connections=0,
                listening_ports=0,
                established_connections=0,
            )

        connections = []
        listening = 0
        ollama_ports = []

        lines = output.split("\n")[2:]

        for line in lines:
            try:
                parts = line.split()
                if len(parts) < 6:
                    continue

                proto = parts[0].lower()
                local = parts[3]
                state = parts[5] if len(parts) > 5 else "LISTEN"

                if ":" in local:
                    local_addr, local_port = local.rsplit(":", 1)
                    try:
                        local_port = int(local_port)
                    except ValueError:
                        continue
                else:
                    continue

                conn = PortConnection(
                    protocol=proto,
                    local_address=local_addr,
                    local_port=local_port,
                    foreign_address="*",
                    foreign_port=0,
                    state=self._parse_state(state),
                    process_name=None,
                    process_pid=None,
                )
                connections.append(conn)
                listening += 1

                if local_port == 11434:
                    ollama_ports.append(11434)

            except Exception:
                pass

        return PortScanResult(
            timestamp=datetime.now(),
            total_connections=len(connections),
            listening_ports=listening,
            established_connections=0,
            connections=connections,
            ollama_ports=list(set(ollama_ports)),
        )

    def scan_all(self) -> Dict[str, PortScanResult]:
        """Scan both Windows and WSL."""
        return {"windows": self.scan_windows(), "wsl": self.scan_wsl()}

    def get_summary(self) -> dict:
        results = self.scan_all()

        summary = {
            "timestamp": datetime.now().isoformat(),
            "windows": {
                "total": results["windows"].total_connections,
                "listening": results["windows"].listening_ports,
                "established": results["windows"].established_connections,
                "ollama_running": len(results["windows"].ollama_ports) > 0,
                "ollama_instances": len(results["windows"].ollama_ports),
            },
            "wsl": {
                "listening": results["wsl"].listening_ports,
                "ollama_running": 11434 in results["wsl"].ollama_ports,
            },
            "suspicious": results["windows"].suspicious[:10],
        }

        return summary

    def count_ollama_instances(self) -> int:
        """Count running Ollama instances in WSL."""
        result = subprocess.run(
            ["wsl", "-d", self.wsl_distro, "pgrep", "-c", "-f", "ollama serve"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except ValueError:
                return 0
        return 0

    def kill_excess_ollama(self, max_instances: int = 3) -> dict:
        """Kill excess Ollama instances, keeping max_instances running."""
        current = self.count_ollama_instances()

        if current <= max_instances:
            return {"killed": 0, "remaining": current, "action": "none"}

        # Get PIDs except the first one
        result = subprocess.run(
            ["wsl", "-d", self.wsl_distro, "pgrep", "-f", "ollama serve"],
            capture_output=True,
            text=True,
        )

        pids = result.stdout.strip().split("\n")
        to_kill = pids[max_instances:]

        killed = 0
        for pid in to_kill:
            if pid:
                subprocess.run(
                    ["wsl", "-d", self.wsl_distro, "kill", pid],
                    capture_output=True,
                )
                killed += 1

        return {
            "killed": killed,
            "remaining": max_instances,
            "action": f"killed_{killed}",
        }


def get_port_scan() -> dict:
    """Quick port scan."""
    scanner = PortScanner()
    return scanner.get_summary()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Port Scanner")
    parser.add_argument("--scan", choices=["windows", "wsl", "all"], default="all")

    args = parser.parse_args()

    scanner = PortScanner()

    if args.scan == "windows":
        result = scanner.scan_windows()
        print(
            f"Windows: {result.total_connections} connections, {result.listening_ports} listening"
        )
    elif args.scan == "wsl":
        result = scanner.scan_wsl()
        print(f"WSL: {result.listening_ports} ports listening")
    else:
        import json

        print(json.dumps(scanner.get_summary(), indent=2, default=str))
