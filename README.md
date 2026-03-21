# Guardian - System Health Monitor

A comprehensive system health monitoring and maintenance package for Windows and WSL.

## Installation

```bash
pip install psutil wmi
```

## Quick Start

```python
from Guardian import run_diagnostics, quick_health_check

# Quick health check
health = quick_health_check()
print(f"CPU: {health['cpu_percent']}%, RAM: {health['ram_percent']}%")

# Full diagnostics (last 7 days)
results = run_diagnostics(days=7, output="report.json", format="json")
```

## Modules

### 1. Diagnostics (`diagnostics.py`)

Analyzes system health, reads event logs, checks crash dumps, and generates reports.

```python
from Guardian import run_diagnostics, DiagnosticsEngine

# Quick usage
results = run_diagnostics(days=30, output="health_report.html", format="html")

# Advanced usage
engine = DiagnosticsEngine()
results = engine.run_full_diagnostics(days=7)

# Access results
print(f"OS: {results.os_version}")
print(f"Uptime: {results.uptime_days:.1f} days")
print(f"Issues: {len(results.issues)}")
print(f"Recommendations: {results.recommendations}")
```

#### Diagnostics Features:
- **Event Log Analysis**: Reads Application, System, and Security logs
- **Crash Dump Analysis**: Finds and reports Minidump/Memdump files
- **Disk Health**: Checks SMART data for disk issues
- **Boot Performance**: Analyzes boot times and errors
- **Performance Metrics**: CPU, RAM, Disk I/O, Network
- **Report Generation**: JSON or HTML output

#### CLI Usage:
```bash
# Run diagnostics, print to console
python -m Guardian.diagnostics --print

# Generate HTML report
python -m Guardian.diagnostics --output report.html --format html --days 30
```

### 2. Windows Guardian (`windows_guardian.py`)

Monitors Windows resources and performs automatic cleanup.

```python
from Guardian import WindowsGuardian, WindowsConfig, CleanupTarget

# Default configuration
config = WindowsConfig(
    ram_threshold=85,
    disk_threshold=90,
    cpu_threshold=90,
    check_interval=300,  # 5 minutes
    auto_heal=True,
    cleanup_targets=[
        CleanupTarget.TEMP_FILES,
        CleanupTarget.RECYCLE_BIN,
        CleanupTarget.DNS_CACHE,
        CleanupTarget.PREFETCH,
    ],
    trigger_wsl_heal=True
)

guardian = WindowsGuardian(config)

# Run once
metrics, needs_healing, cleanup = guardian.run_once()
print(f"CPU: {metrics.cpu_percent}%, RAM: {metrics.ram_percent}%")

# Or run continuous monitoring
guardian.monitor()
```

#### Cleanup Actions:
- `TEMP_FILES` - Clean Windows temp folders
- `RECYCLE_BIN` - Empty Recycle Bin
- `DNS_CACHE` - Flush DNS resolver cache
- `BROWSER_CACHE` - Clear Chrome/Edge/Firefox caches
- `PREFETCH` - Clean Prefetch folder
- `THUMBNAILS` - Clear thumbnail cache
- `WINDOWS_UPDATE` - Clean Windows Update cache

#### CLI Usage:
```bash
# Monitor continuously
python -m Guardian.windows_guardian

# Run once
python -m Guardian.windows_guardian --once

# Run cleanup only
python -m Guardian.windows_guardian --cleanup temp recycle_bin dns

# Custom thresholds
python -m Guardian.windows_guardian --ram-threshold 80 --disk-threshold 85
```

### 3. WSL Guardian (`wsl_guardian.py`)

Monitors WSL resources and performs Linux maintenance.

```python
from Guardian import WSLGuardian, WSLConfig

config = WSLConfig(
    ram_threshold=85,
    disk_threshold=90,
    wsl_distro="Ubuntu",
    check_interval=300,
    auto_heal=True
)

guardian = WSLGuardian(config)

# Run once
metrics, needs_healing = guardian.run_once()

# Or monitor continuously
guardian.monitor()
```

#### CLI Usage:
```bash
# Monitor WSL
python -m Guardian.wsl_guardian

# Run once
python -m Guardian.wsl_guardian --once

# Custom distro
python -m Guardian.wsl_guardian --distro Debian
```

### 4. Unified Guardian

Combines Windows and WSL monitoring with cross-triggering.

```python
from Guardian import Guardian

guardian = Guardian()
guardian.start()  # Runs indefinitely

# Or with custom configs
from Guardian import WSLConfig, WindowsConfig
wsl_cfg = WSLConfig(ram_threshold=80)
win_cfg = WindowsConfig(ram_threshold=80, trigger_wsl_heal=True)
guardian = Guardian(wsl_config=wsl_cfg, windows_config=win_cfg)
guardian.start(duration=3600)  # Run for 1 hour
```

## Common Issues & Solutions

### Boot Problems

1. **Run full diagnostics**:
```bash
python -m Guardian.diagnostics --print
```

2. **Check boot performance**:
```python
from Guardian import DiagnosticsEngine
engine = DiagnosticsEngine()
boot = engine.get_boot_performance()
print(f"Boot time: {boot.total_time_ms/1000:.1f}s")
```

3. **Slow boot recommendations**:
   - Disable startup programs: `msconfig` → Startup
   - Run disk defragmenter
   - Update drivers
   - Consider SSD upgrade

### Disk Issues

1. **Check disk health**:
```python
from Guardian import DiagnosticsEngine
engine = DiagnosticsEngine()
disks = engine.check_disk_health()
for d in disks:
    print(f"{d.model}: {d.health_status}")
```

2. **Run disk cleanup**:
```python
from Guardian import WindowsGuardian, CleanupTarget
guardian = WindowsGuardian()
result = guardian.cleanup([CleanupTarget.TEMP_FILES, CleanupTarget.PREFETCH])
print(f"Freed: {result.space_freed_mb:.1f}MB")
```

3. **Check SMART data**:
```cmd
wmic diskdrive get model,status
```

### Memory Issues

1. **High memory usage**:
```python
from Guardian import quick_health_check
health = quick_health_check()
print(f"RAM: {health['ram_percent']}%")
```

2. **Find memory-hungry processes**:
```python
import psutil
for proc in sorted(psutil.process_iter(['name', 'memory_percent']),
                   key=lambda x: x.info['memory_percent'], reverse=True)[:10]:
    print(f"{proc.info['name']}: {proc.info['memory_percent']:.1f}%")
```

### Crash Analysis

1. **Find crash dumps**:
```python
from Guardian import DiagnosticsEngine
engine = DiagnosticsEngine()
crashes = engine.check_crash_dumps(days=30)
for c in crashes:
    print(f"{c['file']}: {c['size_mb']}MB at {c['timestamp']}")
```

2. **Analyze dumps with WinDbg**:
   - Download WinDbg from Microsoft Store
   - Open dump file: `File > Open Crash Dump`
   - Run: `!analyze -v`

### Temperature Monitoring

```python
import psutil
temps = psutil.sensors_temperatures()
print(temps)
```

## Automated Maintenance Schedule

Create a scheduled task to run daily:

```python
# daily_maintenance.py
from Guardian import cleanup_all, run_diagnostics
import json
from datetime import datetime

# Run cleanup
results = cleanup_all()
print(json.dumps(results, indent=2))

# Weekly diagnostics
if datetime.now().weekday() == 0:  # Monday
    diag = run_diagnostics(days=7, output=f"diagnostics_{datetime.now().date()}.json")
```

Schedule it:
```cmd
schtasks /create /tn "Guardian Maintenance" /tr "python C:\path\to\daily_maintenance.py" /sc daily /st 03:00
```

## File Structure

```
Guardian/
├── __init__.py          # Unified interface
├── wsl_guardian.py      # WSL monitoring
├── windows_guardian.py  # Windows monitoring & cleanup
├── diagnostics.py       # System diagnostics
└── README.md           # This file
```

## Requirements

- Python 3.8+
- psutil
- wmi (optional, for advanced features)
- Administrator privileges (for some cleanup actions)
