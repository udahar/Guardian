#!/usr/bin/env python3
"""
Performance Suggestions Engine - AI-Powered Optimization Advisor
PromptOS Module

Analyzes system state and provides actionable performance suggestions:
- Resource optimization recommendations
- Ollama instance management
- Process prioritization
- Memory/SSD optimization
- Network tuning

Features:
- Context-aware suggestions based on current state
- Pattern-based recommendations
- Priority-ranked actions
- Implementation guidance
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum


class SuggestionCategory(Enum):
    MEMORY = "memory"
    CPU = "cpu"
    DISK = "disk"
    NETWORK = "network"
    OLLAMA = "ollama"
    PROCESS = "process"
    SYSTEM = "system"


class ImpactLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PerformanceSuggestion:
    category: SuggestionCategory
    title: str
    description: str
    action: str
    impact: ImpactLevel
    estimated_improvement: str
    is_automatic: bool = False


class PerformanceAdvisor:
    def __init__(self):
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("PerformanceAdvisor")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def analyze(
        self,
        cpu_percent: float,
        ram_percent: float,
        disk_percent: float,
        wsl_memory_mb: float,
        ollama_instances: int,
        ollama_memory_mb: float,
        high_cpu_procs: List[Dict],
        memory_leaks: List[Dict],
        port_scan: Dict,
        network_status: Dict,
    ) -> List[PerformanceSuggestion]:
        """Analyze all data and generate suggestions."""
        suggestions = []

        # Memory suggestions
        suggestions.extend(
            self._analyze_memory(
                ram_percent, wsl_memory_mb, ollama_memory_mb, memory_leaks
            )
        )

        # CPU suggestions
        suggestions.extend(self._analyze_cpu(cpu_percent, high_cpu_procs))

        # Disk suggestions
        suggestions.extend(self._analyze_disk(disk_percent))

        # Ollama suggestions
        suggestions.extend(
            self._analyze_ollama(ollama_instances, ollama_memory_mb, ram_percent)
        )

        # Network suggestions
        suggestions.extend(self._analyze_network(network_status, port_scan))

        # Sort by impact
        suggestions.sort(
            key=lambda x: (
                ImpactLevel(x.impact.value).value
                if isinstance(x.impact, ImpactLevel)
                else x.impact
            ),
            reverse=True,
        )

        return suggestions

    def _analyze_memory(
        self,
        ram_percent: float,
        wsl_memory_mb: float,
        ollama_memory_mb: float,
        memory_leaks: List[Dict],
    ) -> List[PerformanceSuggestion]:
        suggestions = []

        # High RAM
        if ram_percent > 85:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.MEMORY,
                    title="High Memory Usage",
                    description=f"RAM at {ram_percent}% - system may be swapping",
                    action="Run Windows cleanup: Guardian.cleanup(['temp', 'prefetch'])",
                    impact=ImpactLevel.HIGH,
                    estimated_improvement="10-20% memory freed",
                )
            )

        # WSL high memory
        if wsl_memory_mb > 4000:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.MEMORY,
                    title="WSL Using Excessive Memory",
                    description=f"WSL using {wsl_memory_mb}MB - consider dropping caches",
                    action="wsl -d Ubuntu -u root sh -c 'echo 3 > /proc/sys/vm/drop_caches'",
                    impact=ImpactLevel.MEDIUM,
                    estimated_improvement="500MB-2GB freed",
                )
            )

        # Memory leaks detected
        for leak in memory_leaks[:3]:
            if leak.get("severity") in ["high", "critical"]:
                suggestions.append(
                    PerformanceSuggestion(
                        category=SuggestionCategory.PROCESS,
                        title=f"Memory Leak: {leak.get('name')}",
                        description=leak.get(
                            "description", "Memory growing abnormally"
                        ),
                        action=f"Investigate or restart: {leak.get('name')}",
                        impact=ImpactLevel.CRITICAL,
                        estimated_improvement="Variable - depends on leak",
                    )
                )

        return suggestions

    def _analyze_cpu(
        self, cpu_percent: float, high_cpu_procs: List[Dict]
    ) -> List[PerformanceSuggestion]:
        suggestions = []

        if cpu_percent > 90:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.CPU,
                    title="Critical CPU Usage",
                    description=f"CPU at {cpu_percent}% - system may be unresponsive",
                    action="Identify and terminate high-CPU processes",
                    impact=ImpactLevel.CRITICAL,
                    estimated_improvement="Depends on culprit",
                )
            )

        # Check for specific high-CPU processes
        for proc in high_cpu_procs[:3]:
            name = proc.get("name", "")
            cpu = proc.get("cpu", 0)

            if "ollama" in name.lower() and cpu > 50:
                suggestions.append(
                    PerformanceSuggestion(
                        category=SuggestionCategory.OLLAMA,
                        title=f"Ollama High CPU: {cpu}%",
                        description=f"Ollama process using {cpu}% CPU",
                        action="Consider using smaller model or reducing context",
                        impact=ImpactLevel.MEDIUM,
                        estimated_improvement="20-40% CPU reduction",
                    )
                )

        return suggestions

    def _analyze_disk(self, disk_percent: float) -> List[PerformanceSuggestion]:
        suggestions = []

        if disk_percent > 95:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.DISK,
                    title="Critical Disk Space",
                    description=f"Disk at {disk_percent}% - may cause system instability",
                    action="Run: Guardian.shrink_wsl_disk() + cleanup temp files",
                    impact=ImpactLevel.CRITICAL,
                    estimated_improvement="5-20GB freed",
                )
            )
        elif disk_percent > 90:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.DISK,
                    title="Low Disk Space",
                    description=f"Disk at {disk_percent}% - performance degraded",
                    action="Clean temp files, empty recycle bin, shrink WSL",
                    impact=ImpactLevel.HIGH,
                    estimated_improvement="2-10GB freed",
                )
            )

        return suggestions

    def _analyze_ollama(
        self, instances: int, memory_mb: float, ram_percent: float
    ) -> List[PerformanceSuggestion]:
        suggestions = []

        # Too many instances
        if instances > 2:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.OLLAMA,
                    title=f"Multiple Ollama Instances: {instances}",
                    description="Running multiple Ollama processes wastes resources",
                    action="Kill extra instances: taskkill /F /IM ollama.exe",
                    impact=ImpactLevel.HIGH,
                    estimated_improvement=f"{instances * 2}GB RAM freed",
                )
            )

        # High Ollama memory without keepalive
        if memory_mb > 6000 and ram_percent > 70:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.OLLAMA,
                    title="Ollama Memory Not Released",
                    description=f"Ollama using {memory_mb}MB - may not release on idle",
                    action="Set env: OLLAMA_KEEP_ALIVE=5m (5 minutes) or 0 (immediate release)",
                    impact=ImpactLevel.MEDIUM,
                    estimated_improvement="2-4GB freed when idle",
                )
            )

        # No Ollama running - suggest starting
        if instances == 0 and ram_percent < 50:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.OLLAMA,
                    title="Ollama Not Running",
                    description="AI OS without Ollama - missed opportunities",
                    action="Start Ollama: ollama serve",
                    impact=ImpactLevel.LOW,
                    estimated_improvement="Enable local AI",
                )
            )

        return suggestions

    def _analyze_network(
        self, network_status: Dict, port_scan: Dict
    ) -> List[PerformanceSuggestion]:
        suggestions = []

        # Check for suspicious ports
        suspicious = port_scan.get("suspicious", [])
        if len(suspicious) > 3:
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.NETWORK,
                    title="Multiple Suspicious Ports",
                    description=f"Found {len(suspicious)} potentially risky connections",
                    action="Review: netstat -ano for unusual listening ports",
                    impact=ImpactLevel.MEDIUM,
                    estimated_improvement="Security improvement",
                )
            )

        # Network not reachable
        if not network_status.get("internet_reachable", True):
            suggestions.append(
                PerformanceSuggestion(
                    category=SuggestionCategory.NETWORK,
                    title="No Internet Connection",
                    description="Network unreachable - cloud features disabled",
                    action="Check WiFi/Ethernet or DNS settings",
                    impact=ImpactLevel.HIGH,
                    estimated_improvement="Restore connectivity",
                )
            )

        return suggestions

    def get_suggestions_summary(self, suggestions: List[PerformanceSuggestion]) -> Dict:
        """Get a summary of all suggestions."""
        critical = [s for s in suggestions if s.impact == ImpactLevel.CRITICAL]
        high = [s for s in suggestions if s.impact == ImpactLevel.HIGH]
        medium = [s for s in suggestions if s.impact == ImpactLevel.MEDIUM]
        low = [s for s in suggestions if s.impact == ImpactLevel.LOW]

        return {
            "total": len(suggestions),
            "critical": len(critical),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "can_automatic": sum(1 for s in suggestions if s.is_automatic),
            "top_suggestions": [
                {"title": s.title, "impact": s.impact.value, "action": s.action}
                for s in suggestions[:5]
            ],
        }


def get_performance_suggestions(
    cpu: float,
    ram: float,
    disk: float,
    wsl_memory: float = 0,
    ollama_instances: int = 0,
    ollama_memory: float = 0,
    high_cpu_procs: List[Dict] = None,
    memory_leaks: List[Dict] = None,
    port_scan: Dict = None,
    network_status: Dict = None,
) -> Dict:
    """Quick function to get performance suggestions."""
    advisor = PerformanceAdvisor()

    suggestions = advisor.analyze(
        cpu_percent=cpu,
        ram_percent=ram,
        disk_percent=disk,
        wsl_memory_mb=wsl_memory,
        ollama_instances=ollama_instances,
        ollama_memory_mb=ollama_memory,
        high_cpu_procs=high_cpu_procs or [],
        memory_leaks=memory_leaks or [],
        port_scan=port_scan or {},
        network_status=network_status or {},
    )

    return {
        "suggestions": [
            {
                "category": s.category.value,
                "title": s.title,
                "description": s.description,
                "action": s.action,
                "impact": s.impact.value,
                "improvement": s.estimated_improvement,
            }
            for s in suggestions
        ],
        "summary": advisor.get_suggestions_summary(suggestions),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Performance Advisor")
    parser.add_argument("--cpu", type=float, default=50.0)
    parser.add_argument("--ram", type=float, default=60.0)
    parser.add_argument("--disk", type=float, default=70.0)

    args = parser.parse_args()

    import json

    result = get_performance_suggestions(args.cpu, args.ram, args.disk)
    print(json.dumps(result, indent=2))
