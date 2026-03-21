#!/usr/bin/env python3
"""
Security Monitor - BlueTeam-Inspired Security Monitoring
PromptOS Module

Monitors system security with a health-focused approach:
- Windows Firewall status
- Suspicious process detection
- Network connection analysis
- Unauthorized access attempts
- Security tool awareness (Kali, etc.)

Features:
- Firewall status monitoring
- Suspicious process detection
- Failed login attempt tracking
- Port anomaly detection
- Security recommendations
"""

import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum


try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class SecurityLevel(Enum):
    SECURE = "secure"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityIssue:
    category: str
    severity: SecurityLevel
    title: str
    description: str
    recommendation: str


@dataclass
class SecurityReport:
    timestamp: datetime
    overall_level: SecurityLevel
    firewall_enabled: bool
    issues: List[SecurityIssue]
    suspicious_processes: List[Dict]
    open_ports: List[int]
    security_tools_detected: Dict


class SecurityMonitor:
    """Monitor system security with health focus."""

    def __init__(self):
        self.logger = self._setup_logging()

        # Suspicious process names
        self.suspicious_names = [
            "mimikatz",
            "pwdump",
            "procdump",
            "lsass",
            "psexec",
            "wce",
            "gsecdump",
            "cachedump",
            "netcat",
            "nc",
            "socat",
            "meterpreter",
            "csgo",
            "valve",
            "steam",  # Game hacks commonly
        ]

        # Known security tools (for awareness, not suspicion)
        self.security_tools = {
            "nmap": "Network scanner",
            "metasploit": "Penetration testing",
            "hydra": "Password cracker",
            "john": "Password cracker",
            "aircrack": "WiFi cracker",
            "sqlmap": "SQL injection",
            "nikto": "Web scanner",
            "wireshark": "Packet analyzer",
            "tcpdump": "Packet analyzer",
            "burpsuite": "Web proxy",
            "responder": "LLMNR poisoner",
            "impacket": "Network tools",
        }

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("SecurityMonitor")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_command(self, cmd: list, timeout: int = 15) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def check_firewall(self) -> tuple[bool, bool]:
        """Check Windows Firewall status for domain/private/public."""
        domain = False
        private = False
        public = False

        success, output = self._run_command(
            ["netsh", "advfirewall", "show", "allprofiles", "state"]
        )

        if success:
            for line in output.split("\n"):
                if (
                    "Domain Profile" in line
                    or "Private Profile" in line
                    or "Public Profile" in line
                ):
                    continue
                if (
                    "State                                  ON" in line
                    or "State                             ON" in line
                ):
                    if (
                        "Domain"
                        in output[max(0, output.find(line) - 100) : output.find(line)]
                    ):
                        domain = True
                    elif (
                        "Private"
                        in output[max(0, output.find(line) - 100) : output.find(line)]
                    ):
                        private = True
                    else:
                        public = True

        return domain and private and public, domain

    def detect_suspicious_processes(self) -> List[Dict]:
        """Detect suspicious processes running on system."""
        suspicious = []

        if not PSUTIL_AVAILABLE:
            return suspicious

        try:
            for proc in psutil.process_iter(["name", "pid", "create_time", "cmdline"]):
                try:
                    name = proc.name().lower()

                    # Check against suspicious names
                    for sus in self.suspicious_names:
                        if sus in name:
                            suspicious.append(
                                {
                                    "name": proc.name(),
                                    "pid": proc.pid(),
                                    "reason": f"Suspicious name: {sus}",
                                    "confidence": "high",
                                }
                            )

                    # Check for known hacking tools in command line
                    cmdline = proc.cmdline()
                    if cmdline:
                        cmdline_str = " ".join(cmdline).lower()
                        for tool in self.security_tools:
                            if tool in cmdline_str and tool not in name:
                                suspicious.append(
                                    {
                                        "name": proc.name(),
                                        "pid": proc.pid(),
                                        "reason": f"Running: {tool}",
                                        "confidence": "medium",
                                        "tool": tool,
                                    }
                                )

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except Exception as e:
            self.logger.error(f"Error detecting suspicious processes: {e}")

        return suspicious

    def analyze_network_connections(self) -> Dict:
        """Analyze network connections for anomalies."""
        analysis = {
            "total_connections": 0,
            "established": 0,
            "external": [],
            "listening": [],
            "suspicious": [],
        }

        if not PSUTIL_AVAILABLE:
            return analysis

        suspicious_ips = [
            "45.33.32.156",  # Known scan IP
            "192.99.144",  # Suspicious
        ]

        try:
            for conn in psutil.net_connections():
                analysis["total_connections"] += 1

                if conn.status == "ESTABLISHED":
                    analysis["established"] += 1

                    # Check for external connections
                    if conn.raddr and conn.raddr.ip:
                        ip = conn.raddr.ip
                        if not ip.startswith(
                            ("10.", "127.", "192.168.", "172.", "224.", "239.", "255.")
                        ):
                            analysis["external"].append(
                                {
                                    "ip": ip,
                                    "port": conn.raddr.port,
                                    "process": self._get_process_name(conn.pid),
                                }
                            )

                elif conn.status == "LISTEN":
                    analysis["listening"].append(
                        {
                            "port": conn.laddr.port,
                            "process": self._get_process_name(conn.pid),
                        }
                    )

                    # Check for suspicious ports
                    if conn.laddr.port in [4444, 5555, 6666, 7777, 8888, 31337]:
                        analysis["suspicious"].append(
                            {
                                "port": conn.laddr.port,
                                "reason": "Common metasploit/backup port",
                                "process": self._get_process_name(conn.pid),
                            }
                        )

        except Exception as e:
            self.logger.error(f"Error analyzing connections: {e}")

        return analysis

    def _get_process_name(self, pid: int) -> Optional[str]:
        """Get process name from PID."""
        if not PSUTIL_AVAILABLE or not pid:
            return None
        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def check_user_accounts(self) -> Dict:
        """Check user account security."""
        result = {"local_admins": [], "guest_enabled": False, "last_login_errors": 0}

        # Check local admins
        success, output = self._run_command(["net", "localgroup", "Administrators"])
        if success:
            for line in output.split("\n")[4:]:
                line = line.strip()
                if line and not line.startswith("The command"):
                    result["local_admins"].append(line)

        # Check guest account
        success, output = self._run_command(["net", "user", "Guest"])
        if success and "Account active" in output:
            result["guest_enabled"] = "Yes" in output

        return result

    def check_windows_security(self) -> Dict:
        """Check Windows Security Center status."""
        status = {
            "antivirus": "Unknown",
            "firewall": "Unknown",
            "automatic_updates": "Unknown",
        }

        # Check Windows Security
        success, output = self._run_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-MpComputerStatus | Select-Object -ExpandProperty AntivirusEnabled",
            ]
        )
        if success:
            status["antivirus"] = "Enabled" if "True" in output else "Disabled"

        # Check firewall
        fw_enabled, _ = self.check_firewall()
        status["firewall"] = "Enabled" if fw_enabled else "Disabled"

        # Check updates
        success, output = self._run_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update' | Select-Object -ExpandProperty AuOptions",
            ]
        )
        if success and output.strip():
            status["automatic_updates"] = f"Option {output.strip()}"

        return status

    def get_security_tools(self) -> Dict:
        """Detect installed security/penetration tools."""
        tools = {"detected": [], "warnings": []}

        # Check common locations
        paths = [
            r"C:\Program Files\Nmap",
            r"C:\Tools",
            r"C:\HackTools",
            r"C:\Penetration",
        ]

        for path in paths:
            success, output = self._run_command(["dir", path], timeout=5)
            if success:
                tools["detected"].append(path)

        # Check WSL for Kali tools
        success, output = self._run_command(["wsl", "-l", "-v"])
        if success and "kali" in output.lower():
            tools["warnings"].append(
                "Kali Linux detected in WSL - ensure proper network isolation"
            )

        return tools

    def generate_report(self) -> SecurityReport:
        """Generate comprehensive security report."""
        issues = []

        # Check firewall
        fw_enabled, _ = self.check_firewall()
        if not fw_enabled:
            issues.append(
                SecurityIssue(
                    category="firewall",
                    severity=SecurityLevel.HIGH,
                    title="Windows Firewall Disabled",
                    description="Firewall is not enabled for all profiles",
                    recommendation="Enable Windows Firewall: netsh advfirewall set allprofiles state on",
                )
            )

        # Check suspicious processes
        suspicious = self.detect_suspicious_processes()
        if suspicious:
            for sus in suspicious[:3]:  # Top 3
                issues.append(
                    SecurityIssue(
                        category="process",
                        severity=SecurityLevel.MEDIUM,
                        title=f"Suspicious Process: {sus['name']}",
                        description=sus["reason"],
                        recommendation="Investigate if this process is legitimate",
                    )
                )

        # Network analysis
        net_analysis = self.analyze_network_connections()

        # Check security status
        security_status = self.check_windows_security()

        # Determine overall level
        level = SecurityLevel.SECURE
        if any(i.severity == SecurityLevel.CRITICAL for i in issues):
            level = SecurityLevel.CRITICAL
        elif any(i.severity == SecurityLevel.HIGH for i in issues):
            level = SecurityLevel.HIGH
        elif any(i.severity == SecurityLevel.MEDIUM for i in issues):
            level = SecurityLevel.MEDIUM

        return SecurityReport(
            timestamp=datetime.now(),
            overall_level=level,
            firewall_enabled=fw_enabled,
            issues=issues,
            suspicious_processes=suspicious,
            open_ports=[p["port"] for p in net_analysis["listening"]],
            security_tools_detected=self.get_security_tools(),
        )


def get_security_report() -> dict:
    """Quick security report."""
    monitor = SecurityMonitor()
    report = monitor.generate_report()

    return {
        "timestamp": report.timestamp.isoformat(),
        "level": report.overall_level.value,
        "firewall": report.firewall_enabled,
        "issues": [
            {
                "category": i.category,
                "severity": i.severity.value,
                "title": i.title,
                "recommendation": i.recommendation,
            }
            for i in report.issues
        ],
        "suspicious_count": len(report.suspicious_processes),
        "open_ports": report.open_ports[:20],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Security Monitor")
    parser.add_argument("--report", action="store_true", help="Full security report")
    parser.add_argument(
        "--processes", action="store_true", help="Check suspicious processes"
    )
    parser.add_argument("--network", action="store_true", help="Analyze network")

    args = parser.parse_args()

    monitor = SecurityMonitor()

    if args.report or (not any([args.processes, args.network])):
        import json

        print(json.dumps(get_security_report(), indent=2, default=str))

    elif args.processes:
        suspicious = monitor.detect_suspicious_processes()
        print(f"Suspicious processes: {len(suspicious)}")
        for s in suspicious:
            print(f"  {s['name']} (PID: {s['pid']}) - {s['reason']}")

    elif args.network:
        import json

        print(json.dumps(monitor.analyze_network_connections(), indent=2))
