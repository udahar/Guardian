# Codex Guardian Import Audit Progress Report

Date: 2026-05-23
Auditor: Codex
Scope: First-pass evidence audit of `import/Guardian` Python import into `eggs/system-guardian-*`.

## Executive Summary

Claude's `IMPORT_PROGRESS_REPORT.md` is useful, but it is not complete enough to be treated as a migration ledger.

The good news: many of the gaps listed in Claude's report now have Go files, routes, and some COBOL policy coverage in the target Guardian eggs. The six main Guardian eggs compile with `go test ./...`.

The problem: the report only accounts for 30 of the 43 `_imported.py` source files. Thirteen imported Python files are not mentioned at all. That means the current report cannot prove all production Guardian behavior survived the port.

Current status: **partially ported, compile-clean, not yet migration-complete**.

## Audit Method

- Counted all `_imported.py` files under `import/Guardian`.
- Compared source files against `IMPORT_PROGRESS_REPORT.md`.
- Checked expected target egg files under `eggs/system-guardian-*`.
- Searched for claimed endpoints and COBOL policy names.
- Ran `go test ./...` in:
  - `system-guardian-health-v1/runtime`
  - `system-guardian-perf-v1/runtime`
  - `system-guardian-security-v1/runtime`
  - `system-guardian-wsl-v1/runtime`
  - `system-guardian-docker-v1/runtime`
  - `system-guardian-alerts-v1/runtime`
- Spot-checked key Go files for source behavior preservation.

Generated supporting machine report:

- `import/Guardian/codex_guardian_symbol_audit.json`

## Build/Compile Status

All checked Guardian runtime packages compile:

| Egg | Result |
|---|---|
| `system-guardian-health-v1` | `go test ./...` passes, no test files |
| `system-guardian-perf-v1` | `go test ./...` passes, no test files |
| `system-guardian-security-v1` | `go test ./...` passes, no test files |
| `system-guardian-wsl-v1` | `go test ./...` passes, no test files |
| `system-guardian-docker-v1` | `go test ./...` passes, no test files |
| `system-guardian-alerts-v1` | `go test ./...` passes, no test files |

Important: compile-clean is not the same as import-complete. There are currently no Go tests proving Python behavior parity.

## Report Coverage Gap

There are 43 Python files marked `_imported.py`.

Claude's report mentions 30.

These 13 source files are not accounted for in the report:

| Unaccounted Source File | Risk |
|---|---|
| `modules/alerts/alfred_bridge_imported.py` | Alert bridge behavior may be lost or only partially mapped |
| `modules/alerts/telegram_alerts_imported.py` | Telegram alert routing may be incomplete |
| `modules/disk/disk_audit_imported.py` | Disk audit behavior may be duplicated or missed |
| `modules/docker/docker_guardian_imported.py` | Docker lifecycle/cleanup behavior may be incompletely represented |
| `modules/network/network_monitor_imported.py` | Network monitoring behavior needs explicit receipt |
| `modules/network/port_scanner_imported.py` | Port scan behavior needs explicit receipt |
| `modules/performance/performance_advisor_imported.py` | Advisor/recommendation logic may be missing |
| `modules/services/service_health_imported.py` | Service health checks need explicit receipt |
| `modules/windows/windows_guardian_imported.py` | Windows-specific cleanup/maintenance may be missing |
| `modules/wsl/vhd_compact_imported.py` | VHD compact behavior may be only partially preserved |
| `modules/wsl/wsl_guardian_imported.py` | WSL orchestration behavior needs explicit receipt |
| `modules/wsl/wsl_manager_imported.py` | WSL management behavior needs explicit receipt |
| `modules/wsl/wsl_utils_imported.py` | Shared WSL utility behavior needs explicit receipt |

This is the biggest audit finding. The source files may be partially represented in eggs, but they are not documented as migrated, excluded, or intentionally superseded.

## Gap Status From Claude Report

| Gap | Claimed Target | Evidence Found | Audit Status |
|---|---|---|---|
| GAP 1 Memory pressure/thrashing | `system-guardian-perf-v1` | `runtime/memory_pressure.go`, `/api/guardian/memory-pressure`, `THRASH-POLICY` exist | Mostly implemented; needs runtime test on Windows counters |
| GAP 2 Log watcher + DB health | `system-guardian-health-v1` | `runtime/logwatch.go`, `/api/guardian/log-scan`, `/api/guardian/db-health` exist | Partially implemented; lacks Security log, WSL/app log scan evidence, no COBOL `LOG-SEVERITY` |
| GAP 3 Thermal watchdog | `system-guardian-health-v1` | `runtime/thermal.go`, `/api/guardian/thermal` exist | Partially implemented; no COBOL `THERMAL-POLICY`, uses Go policy |
| GAP 4 Runaway process detection | `system-guardian-perf-v1` | `runtime/runaway.go`, `/api/guardian/runaway-scan`, `RUNAWAY-POLICY` exist | Mostly implemented; needs kill/cooldown safety audit |
| GAP 5 Cleaner/audit targets | `system-guardian-perf-v1` | `cleaner.go` expanded; `diskaudit.go` exists | Partially implemented; no `diskaudit_extra.go`, no `STALE-POLICY`, project-level stale scanner incomplete |
| GAP 6 Docker daemon.json | `system-guardian-docker-v1` | `daemon_config.go`, `/api/guardian/docker-daemon-config`, `/api/guardian/docker-log-sizes` exist | Implemented enough for audit pass; needs destructive-write safety review |
| GAP 7 Diagnostics engine | `system-guardian-health-v1` | `diagnostics.go` exists | Route mismatch: code defines `handleFullDiagnostics`, but `main.go` does not mount `/api/guardian/diagnostics` |
| GAP 8 Memory leak detector | `system-guardian-perf-v1` | `leak_detect.go`, `LEAK-POLICY` exist | Partially implemented; endpoint is `/api/guardian/leak-check`, not report's `/api/guardian/leak-scan` |
| GAP 9 WSL in-distro monitoring | `system-guardian-wsl-v1` | `wsl_sensors.go`, `/api/guardian/wsl-sensors` exist | Partially implemented; no `/api/guardian/wsl-oom-scan`, no COBOL `OOM-POLICY` or `ZOMBIE-POLICY` |
| GAP 10 WSL reclamation | `system-guardian-wsl-v1` | `reclaim.go`, `/api/guardian/wsl-reclaim-status`, `/api/guardian/wsl-reclaim` exist | Partially implemented; no COBOL `RECLAIM-POLICY`, route name differs from report |
| GAP 11 Security enrichment | `system-guardian-security-v1` | `security_extra.go`, `/net-anomalies`, `/security-center`, `/security-tools` exist | Partially implemented; no `NET-ANOMALY` or `ACCOUNT-POLICY` COBOL commands |
| GAP 12 Stale cache scanner | `system-guardian-perf-v1` | Some cleanup targets added | Still incomplete; not a full stale project scanner |

## Specific Findings

### Finding 1: Claude's report is stale relative to code

The report says:

> Status: IN PROGRESS — gaps identified, work not yet started

But the target eggs now contain files such as:

- `system-guardian-perf-v1/runtime/memory_pressure.go`
- `system-guardian-perf-v1/runtime/runaway.go`
- `system-guardian-perf-v1/runtime/leak_detect.go`
- `system-guardian-health-v1/runtime/logwatch.go`
- `system-guardian-health-v1/runtime/thermal.go`
- `system-guardian-health-v1/runtime/diagnostics.go`
- `system-guardian-docker-v1/runtime/daemon_config.go`
- `system-guardian-wsl-v1/runtime/wsl_sensors.go`
- `system-guardian-wsl-v1/runtime/reclaim.go`
- `system-guardian-security-v1/runtime/security_extra.go`

The report needs to be updated from "work to build" into an actual import ledger.

### Finding 2: Diagnostics endpoint is not mounted

`system-guardian-health-v1/runtime/diagnostics.go` defines:

- `handleFullDiagnostics`
- `runFullDiagnostics`

But `system-guardian-health-v1/runtime/main.go` mounts:

- `/api/guardian/diagnose`

It does not mount:

- `/api/guardian/diagnostics`

This means the full diagnostics engine may compile but not be reachable through the claimed endpoint.

### Finding 3: Several COBOL policy commands promised in the report do not exist

Missing or renamed:

- `LOG-SEVERITY`
- `THERMAL-POLICY`
- `DIAG-SEVERITY`
- `STALE-POLICY`
- `OOM-POLICY`
- `ZOMBIE-POLICY`
- `RECLAIM-POLICY`
- `NET-ANOMALY`
- `ACCOUNT-POLICY`

Some of this logic exists in Go fallback functions, but that violates the stated architecture intent where durable policy belongs in COBOL where appropriate.

### Finding 4: WSL functionality is partially ported but not fully shaped

Good:

- `wsl_sensors.go` checks load average, zombies, OOM lines, FD leaks, and disk I/O.
- `reclaim.go` covers vmmem/free gap, `drop_caches`, `fstrim`, and journal vacuum.

Still missing from the report's shape:

- dedicated `/api/guardian/wsl-oom-scan`
- COBOL `OOM-POLICY`
- COBOL `ZOMBIE-POLICY`
- COBOL `RECLAIM-POLICY`
- explicit receipt for `wsl_utils_imported.py`, `wsl_manager_imported.py`, `wsl_guardian_imported.py`, and `vhd_compact_imported.py`

### Finding 5: Project-level cache/stale scanner is incomplete

`cleaner.go` includes useful new targets:

- WER reports
- Minidumps
- Prefetch
- SoftwareDistribution downloads
- thumbnail cache
- Cargo registry
- Gradle caches
- stale `.parts`

But there is no separate `diskaudit_extra.go`, no `STALE-POLICY`, and no evident full project-level scanner for:

- `node_modules` with staleness
- `.next`
- `dist`
- `build`
- Rust `target`
- `.tsbuildinfo`
- `.pytest_cache`
- Maven/Ruby/Composer caches

This matters because Richard's main pain point is SSD exhaustion from development artifacts.

### Finding 6: Security enrichment exists but policy architecture is incomplete

`security_extra.go` adds useful endpoint work:

- network anomaly scan
- Windows Security Center
- tool detection

But it does not add the report's COBOL commands:

- `NET-ANOMALY`
- `ACCOUNT-POLICY`

It also does not prove failed login tracking or local admin/guest account audit parity from the Python source.

## Current Egg Health Summary

| Egg | Audit State |
|---|---|
| `system-guardian-health-v1` | Active work present; diagnostics endpoint/policy gaps remain |
| `system-guardian-network-v1` | Exists and likely covers some unmentioned files, but not in Claude's report |
| `system-guardian-perf-v1` | Strongest port so far; memory/runaway/leak compile; stale project scanner still incomplete |
| `system-guardian-security-v1` | Enrichment present; COBOL policy and account/login parity uncertain |
| `system-guardian-wsl-v1` | Useful WSL sensors/reclaim present; source utility files not fully receipted |
| `system-guardian-docker-v1` | Daemon/log management present; needs safety review for writes |
| `system-guardian-alerts-v1` | Exists; source alert files not receipted in Claude's report |

## Required Next Audit Batch

Before deleting or archiving any Guardian source file, create a receipt for every one of the 13 unaccounted files.

Recommended next batch order:

1. `system-guardian-network-v1`
   - `modules/network/network_monitor_imported.py`
   - `modules/network/port_scanner_imported.py`
   - `modules/services/service_health_imported.py`

2. `system-guardian-alerts-v1`
   - `modules/alerts/alfred_bridge_imported.py`
   - `modules/alerts/telegram_alerts_imported.py`

3. `system-guardian-wsl-v1`
   - `modules/wsl/vhd_compact_imported.py`
   - `modules/wsl/wsl_guardian_imported.py`
   - `modules/wsl/wsl_manager_imported.py`
   - `modules/wsl/wsl_utils_imported.py`

4. `system-guardian-perf-v1`
   - `modules/disk/disk_audit_imported.py`
   - `modules/performance/performance_advisor_imported.py`

5. `system-guardian-docker-v1`
   - `modules/docker/docker_guardian_imported.py`

6. `system-guardian-health-v1` or a dedicated Windows egg
   - `modules/windows/windows_guardian_imported.py`

## Guardian Upgrade Retrospective

These upgrades should be considered after the import ledger is complete.

### 1. Import Ledger Enforcement

Add a machine-readable `guardian_import_ledger.sqlite` or `guardian_import_ledger.json` with:

- source file
- target egg
- target file(s)
- imported functions/classes
- intentionally excluded functions/classes
- verification command
- verification result
- reviewer
- timestamp

No `_imported.py` file should be considered complete without a ledger row.

### 2. Guardian Safety Modes

Every destructive action should expose:

- `dry_run=true`
- `explain=true`
- `require_admin=true/false`
- `risk=safe|rebuild|risky|dangerous`
- `estimated_freed_gb`
- `last_run_at`
- `cooldown_until`

This is especially important for:

- Docker prune
- WSL reclaim
- cache cleanup
- runaway process kill
- Windows update cache cleanup

### 3. Unified Guardian Hub

Keep eggs separate, but add one read-only aggregator dashboard/API that polls:

- health
- perf
- network
- security
- WSL
- Docker
- alerts

The hub should not own cleanup logic. It should summarize state and dispatch approved actions to the owning egg.

### 4. Low Disk Emergency Mode

Add a policy mode for Richard's real failure case: disk free under 1GB.

Suggested stages:

- `< 10GB`: warn and prepare cleanup plan
- `< 5GB`: auto-clean safe caches
- `< 1GB`: emergency safe cleanup, stop known thrashers, warn loudly
- `< 300MB`: freeze nonessential workers and block large builds/downloads

### 5. Runaway Process Spawn Guard

Track process spawn bursts:

- same executable spawning repeatedly
- same command line spawning repeatedly
- child process trees from Claude/Codex/dev servers
- orphaned browser/node/python/go processes

This would have helped with the previous looping process problem.

### 6. Build Artifact Census

Add a development artifact scanner that understands repo shapes:

- Node: `node_modules`, `.next`, `dist`, `build`, `.turbo`
- Rust: `target`
- Go: build/test cache
- Python: `.venv`, `__pycache__`, `.pytest_cache`, pip/uv cache
- .NET: `bin`, `obj`, NuGet cache
- Docker: images, containers, volumes, logs

The scanner should produce a cleanup plan first, not delete immediately.

## Current Recommendation

Do not declare Guardian port complete.

Do not delete original Guardian Python files.

Next step should be a focused receipt audit of the 13 unaccounted files, starting with the network egg because it likely already contains some of that behavior but Claude's report failed to document it.

## 2026-05-23 Follow-Up Repair Pass: Disk/SSD Bloat Coverage

Richard specifically asked whether the original Guardian cleanup value survived, especially common SSD bloat locations. I treated `_imported` suffixes as unreliable and compared the original Python cleanup behavior against the current eggs.

### Files Changed

- `eggs/system-guardian-perf-v1/runtime/cleaner.go`
- `eggs/system-guardian-perf-v1/runtime/cleaner_ops.go`
- `eggs/system-guardian-perf-v1/runtime/caches.go`
- `eggs/system-guardian-docker-v1/runtime/docker.go`
- `eggs/system-guardian-wsl-v1/runtime/wsl.go`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| Explorer thumbnail cleanup was too broad | Go cleaner used generic directory cleanup for the Explorer cache folder | Added `cleanThumbnailCache`, deleting only `thumbcache*` and `iconcache*` files like the Python original | Special cleanup targets need dedicated handlers when the source only deleted selected files |
| Download fragment cleanup was too aggressive | Go cleaner matched partial files without the Python age gate and included generic `.tmp` files | Added 14-day age threshold and removed broad `.tmp` matching from Downloads cleanup | Never delete user download fragments without an age threshold |
| Firefox cache cleanup was missing source behavior | Python handled Firefox profile `cache2`; Go only had Chrome and Edge | Added `firefox-cache` target and profile-aware `cleanFirefoxCache` | Browser cleanup must handle profile-based browsers explicitly |
| Brave and Opera cache locations were missing | Current app usage includes Chromium-family browsers beyond Chrome/Edge | Added Brave and Opera cache targets | Browser cache registry should include Richard's active browsers |
| Claude VM bundle path was wrong | Go used `LOCALAPPDATA\AnthropicClaude`; Python used `APPDATA\Claude\vm_bundles` | Corrected `claude-vmbundles` target and added Claude Code session logs | Source path constants must be checked against original Python, not guessed |
| Local WER reports were missing | Go only included ProgramData WER locations | Added `%LOCALAPPDATA%\Microsoft\Windows\WER` | Include both machine-wide and user-local Windows reporting paths |
| Project cache scanner was incomplete | `scanCaches` only covered package caches, temp, and Go build cache | Added project scans for `node_modules`, `.next`, `.pytest_cache`, JS `dist/build`, Rust `target`, plus Composer/Maven/Ruby/Cargo git caches | Guardian needs both cleanup targets and read-only disk census for development artifacts |
| Docker VHD detection was too narrow | Go only checked `docker_data.vhdx` | Added `docker-desktop-data.vhdx` fallback | Docker Desktop VHD names vary by version |
| WSL VHD scan could panic on short directory names | Go sliced `e.Name()[:8]` without checking length | Added safe label truncation | Never slice path-derived labels without length checks |
| WSL VHD scan missed alternate Docker VHD name | Same Docker naming issue existed in WSL egg VHD inventory | Added both Docker VHD candidates to WSL VHD scanner | Shared storage facts must be represented consistently across eggs |

### Current Perf Cleanup Target Receipt

The performance egg now exposes these cleanup target IDs:

- `onedrive-logs`
- `onedrive-listsync`
- `onedrive-settings`
- `onedrive-versioncache`
- `windows-temp`
- `npm-cache`
- `pip-cache`
- `uv-cache`
- `nuget-cache`
- `yarn-cache`
- `pnpm-store`
- `go-build-cache`
- `go-mod-cache`
- `chrome-cache`
- `edge-cache`
- `brave-cache`
- `opera-cache`
- `firefox-cache`
- `pycache-all`
- `claude-vmbundles`
- `claude-code-sessions`
- `wer-local`
- `wer-reports`
- `wer-archive`
- `minidumps`
- `prefetch`
- `softdist-dl`
- `thumbnails`
- `stale-parts`
- `cargo-registry`
- `gradle-caches`
- `cursor-cache`

### Verification

Compile checks passed:

- `system-guardian-perf-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-docker-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-wsl-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-health-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-security-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-alerts-v1/runtime`: `go test ./...` passes, no test files

This still does not prove behavior parity. It proves the repaired Go code compiles.

### Remaining Disk/Cleanup Gaps

- No automated test yet proves dry-run cleanup plans are non-destructive.
- No shared safety contract yet requires every destructive endpoint to support `dry_run`.
- Docker prune endpoint still performs real pruning when called; it should grow a dry-run/planning endpoint before being treated as production-safe.
- WSL/Docker VHD compaction is still mostly inventory/reclaim-adjacent in the eggs; the original elevated scheduled-task compaction workflow needs a separate safety audit before porting.
- `windows_guardian_imported.py` should remain unarchived until health/perf eggs explicitly receipt CPU/RAM/disk threshold healing and WSL-trigger behavior.

## 2026-05-23 Follow-Up Repair Pass: Network Monitor Coverage

`modules/network/network_monitor_imported.py` was one of the files not accounted for in Claude's report. The network egg had port scanning and service checks, but it did not preserve the original internet/DNS/tunnel health behavior.

### Files Changed

- `eggs/system-guardian-network-v1/runtime/main.go`
- `eggs/system-guardian-network-v1/runtime/network_health.go`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| Internet reachability check was missing | Network egg only scanned ports/services | Added `GET /api/guardian/network-health` with ping latency check | Network health must include connectivity, not only local ports |
| DNS health check was missing | Python fallback used HTTPS/nslookup; Go had no equivalent | Added HTTPS check with `nslookup` fallback | DNS failure is a distinct Guardian condition |
| Tailscale/Cloudflare Tunnel checks were missing | Tunnel behavior from Python was not ported | Added Tailscale status and Cloudflare process/tunnel check | Tunnel status is first-class network health state |
| Interface inventory was missing | Python parsed `ipconfig`; Go had no interface inventory | Added local IPv4 interface collection via `net.Interfaces` | Use structured OS APIs before shell parsing where practical |

### Verification

- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files

### Remaining Network Gaps

- Original Python could attempt Cloudflare service restart; the Go port is currently read-only for this path.
- Port scanner parity still needs a deeper pass for WSL port scanning, established external connection reporting, and Ollama process-spawn controls.
- `service_health_imported.py` still needs a service registry audit because its original list includes stack services that may not match the current egg registry.

## 2026-05-23 Follow-Up Repair Pass: Safe-By-Default Destructive Actions

Richard clarified the production goal: Guardian should clean the Windows machine with little to no risk. I therefore changed the risky action surfaces to plan-only by default.

### Files Changed

- `eggs/system-guardian-perf-v1/runtime/cleaner.go`
- `eggs/system-guardian-docker-v1/runtime/docker.go`
- `eggs/system-guardian-docker-v1/runtime/main.go`
- `eggs/system-guardian-wsl-v1/runtime/main.go`
- `eggs/system-guardian-wsl-v1/runtime/wsl.go`
- `eggs/system-guardian-wsl-v1/runtime/reclaim.go`
- `eggs/system-guardian-network-v1/runtime/services.go`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| `POST /api/guardian/clean` executed when `dry_run` was omitted | Boolean default in Go is false | Changed `dry_run` to pointer semantics and defaulted missing value to `true` | Destructive endpoints must be safe-by-default |
| Docker prune endpoint executed real prune immediately | No dry-run/planning mode | `POST /api/guardian/docker-prune` now defaults to plan-only; execution requires `dry_run=false` | Docker cleanup must require explicit execution |
| WSL reclaim endpoint executed immediately | No dry-run/planning mode | `POST /api/guardian/wsl-reclaim` now defaults to plan-only | WSL maintenance actions must be visible before execution |
| WSL heal endpoint executed immediately | Same issue as reclaim | `POST /api/guardian/wsl-heal` now defaults to plan-only | Even low-risk Linux cleanup should not surprise the operator |
| Service health alerting was too noisy | Every down service was treated as alert-worthy | Added `optional` service metadata and made only core Guardian eggs alert by default | Development-only services should be monitored without panic alerts |
| Guardian service registry was incomplete | WSL, Docker, and alerts eggs were missing from network service health | Added all seven Guardian eggs to the registry | Guardian should monitor its own eggs explicitly |

### Safe Execution Contract

These endpoints now require explicit execution intent:

- `POST /api/guardian/clean` with `{"dry_run": false, "targets": [...]}` to delete
- `POST /api/guardian/docker-prune` with `{"dry_run": false}` to prune
- `POST /api/guardian/wsl-heal` with `{"dry_run": false}` to run WSL heal
- `POST /api/guardian/wsl-reclaim` with `{"dry_run": false}` to run reclaim

If `dry_run` is omitted, these endpoints return a plan.

### Verification

All Guardian runtime eggs compile:

- `system-guardian-alerts-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-docker-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-health-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-perf-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-security-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-wsl-v1/runtime`: `go test ./...` passes, no test files

### Remaining Safety Work

- Add actual Go tests for the default-dry-run behavior.
- Add a shared Guardian action schema with `risk`, `requires_admin`, `estimated_freed_gb`, `cooldown`, and `last_run_at`.
- Add a single read-only Guardian dashboard endpoint that aggregates all egg status without owning cleanup logic.
- Add Windows emergency low-disk policy stages, but keep execution gated behind the safe-by-default contract.

## 2026-05-23 Follow-Up Repair Pass: Help, SQLite Status, And Alerts

Richard requested operator/AI-facing instructions, scan logging, current status reporting, and alert hooks. This pass documents the runtime surfaces and closes the missing SQLite persistence gaps in the eggs that already had schemas but did not write them.

### HTML Status

Each Guardian egg now ships a small `runtime/status.html` and serves it from:

- `/`
- `/guardian.html`

The page fetches `/api/guardian/status` and refreshes every 15 seconds. The current operator/AI audit surface is therefore HTML for humans, JSON for tools, and SQLite for durable history:

- `../memory/egg_state.db`
- `../memory/egg_state.sql`

This keeps the HTML view as a thin renderer instead of a second source of truth.

### Files Changed

- `eggs/system-guardian-alerts-v1/runtime/main.go`
- `eggs/system-guardian-alerts-v1/runtime/alerter.go`
- `eggs/system-guardian-alerts-v1/runtime/db.go`
- `eggs/system-guardian-alerts-v1/runtime/html.go`
- `eggs/system-guardian-alerts-v1/runtime/status.html`
- `eggs/system-guardian-alerts-v1/runtime/go.mod`
- `eggs/system-guardian-alerts-v1/runtime/go.sum`
- `eggs/system-guardian-docker-v1/runtime/main.go`
- `eggs/system-guardian-docker-v1/runtime/db.go`
- `eggs/system-guardian-docker-v1/runtime/html.go`
- `eggs/system-guardian-docker-v1/runtime/status.html`
- `eggs/system-guardian-docker-v1/runtime/main_test.go`
- `eggs/system-guardian-docker-v1/runtime/go.mod`
- `eggs/system-guardian-docker-v1/runtime/go.sum`
- `eggs/system-guardian-health-v1/runtime/main.go`
- `eggs/system-guardian-health-v1/runtime/html.go`
- `eggs/system-guardian-health-v1/runtime/status.html`
- `eggs/system-guardian-network-v1/runtime/main.go`
- `eggs/system-guardian-network-v1/runtime/html.go`
- `eggs/system-guardian-network-v1/runtime/status.html`
- `eggs/system-guardian-perf-v1/runtime/main.go`
- `eggs/system-guardian-perf-v1/runtime/html.go`
- `eggs/system-guardian-perf-v1/runtime/status.html`
- `eggs/system-guardian-security-v1/runtime/main.go`
- `eggs/system-guardian-security-v1/runtime/html.go`
- `eggs/system-guardian-security-v1/runtime/status.html`
- `eggs/system-guardian-wsl-v1/runtime/main.go`
- `eggs/system-guardian-wsl-v1/runtime/reclaim.go`
- `eggs/system-guardian-wsl-v1/runtime/db.go`
- `eggs/system-guardian-wsl-v1/runtime/html.go`
- `eggs/system-guardian-wsl-v1/runtime/status.html`
- `eggs/system-guardian-wsl-v1/runtime/main_test.go`
- `eggs/system-guardian-wsl-v1/runtime/go.mod`
- `eggs/system-guardian-wsl-v1/runtime/go.sum`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| `--help` existed but did not explain operation | Import created minimal startup help only | Expanded help across all seven Guardian eggs with purpose, safety, endpoints, and SQLite path | Every executable egg needs operator-facing `--help` |
| Alerts schema existed but runtime did not write it | `recentAlerts()` was still a placeholder | Added SQLite persistence for `alerts_sent` and wired `/api/guardian/alerts` | Existing schemas must be live, not decorative |
| Docker schema existed but runtime did not write scan/prune state | Disk/prune handlers returned JSON only | Added SQLite writes for `docker_disk_state` and `prune_history` | Scan/report APIs must leave an audit trail |
| WSL schema existed but runtime did not write distro/VHD/heal state | WSL handlers returned JSON only | Added SQLite writes for `wsl_distros`, `vhd_snapshots`, and `heal_ops` | Machine repair actions need durable history |
| No single current-status API on new persistence surfaces | Existing endpoints were split by function | Added `/api/guardian/status` to alerts, Docker, and WSL | Each egg should expose a current audit summary |
| Telegram route was declared conceptually but not implemented | Alert routing returned `popup+telegram` for critical without sending Telegram | Added env-based Telegram delivery using `GUARDIAN_TELEGRAM_BOT_TOKEN`/`GUARDIAN_TELEGRAM_CHAT_ID` or generic `TELEGRAM_*` | Alert routes must either work or report unavailable |
| Default dry-run behavior had no tests | Safety was implementation-only | Added tests for Docker and WSL dry-run parsing/defaults | Dangerous endpoint defaults require tests |
| Human audit pages were missing | Eggs exposed API state only | Added `runtime/status.html` and mounted it at `/` and `/guardian.html` | Each operator-facing egg should have a minimal human status page |
| `/api/guardian/status` was not uniform | Some eggs only exposed specialized endpoints | Added current-status routes across all seven eggs | Shared dashboard pages need stable, predictable status routes |

### Alert Channels

Current alert behavior:

- Windows popup: implemented through PowerShell `System.Windows.Forms.NotifyIcon`
- Telegram: implemented if bot token and chat ID are present in environment
- Alfred bridge: not restored because Alfred bridge no longer exists in its previous form

Supported Telegram environment variables:

- `GUARDIAN_TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN`
- `GUARDIAN_TELEGRAM_CHAT_ID` or `TELEGRAM_CHAT_ID`

### Verification

All Guardian runtime eggs compile and tests pass:

- `system-guardian-alerts-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-docker-v1/runtime`: `go test ./...` passes
- `system-guardian-health-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-perf-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-security-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-wsl-v1/runtime`: `go test ./...` passes

`go run . --help` was smoke-tested across all seven Guardian eggs.

Every Guardian egg now has:

- `GET /`
- `GET /guardian.html`
- `GET /api/guardian/status`

### Remaining Upgrade Work

- Add tests for alert SQLite persistence and Telegram-not-configured behavior.
- Add DB-backed retention/cooldown policy so scan logs do not grow forever.
- Add a richer action schema: risk, admin requirement, planned paths, estimated freed bytes, execution cooldown, and last result.

## 2026-05-23 Follow-Up Repair Pass: Guardian Supervisor Egg

Richard asked for the remaining reporting work to continue and for the report to stay current for Claude. This pass adds a supervisor egg that can be used by a human or AI to audit the Guardian set from one place.

### Files Added

- `eggs/system-guardian-supervisor-v1/egg.toml`
- `eggs/system-guardian-supervisor-v1/behavior/contract.feature`
- `eggs/system-guardian-supervisor-v1/logic/main.cbl`
- `eggs/system-guardian-supervisor-v1/memory/egg_state.sql`
- `eggs/system-guardian-supervisor-v1/runtime/main.go`
- `eggs/system-guardian-supervisor-v1/runtime/scanner.go`
- `eggs/system-guardian-supervisor-v1/runtime/db.go`
- `eggs/system-guardian-supervisor-v1/runtime/html.go`
- `eggs/system-guardian-supervisor-v1/runtime/status.html`
- `eggs/system-guardian-supervisor-v1/runtime/scanner_test.go`
- `eggs/system-guardian-supervisor-v1/runtime/go.mod`
- `eggs/system-guardian-supervisor-v1/runtime/go.sum`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| Guardian had per-egg status but no single audit surface | Each egg exposed its own HTML/API | Added `system-guardian-supervisor-v1` on port `18947` | Multi-egg systems need one read-only operator summary |
| Aggregation could have become HTTP-to-HTTP glue | Easy path would poll every child API | Supervisor reads sibling `memory/egg_state.db` files directly and only uses TCP liveness checks | Internal status aggregation should prefer local SQLite/file state |
| Supervisor activity was not durable | No supervisor memory schema existed | Added `supervisor_scans` table with aggregate JSON | Supervisor audits should leave a trail |
| Human dashboard was missing | Previous HTML existed per child egg only | Added supervisor `runtime/status.html` at `/` and `/guardian.html` | Human status pages should be thin renderers over JSON status |
| No tests existed for supervisor helpers | New scanner code needed basic regression checks | Added tests for identifier quoting and supervisor port registration | SQLite helper safety should be tested |

### Supervisor Behavior

`system-guardian-supervisor-v1` is read-only.

It reports:

- Guardian egg IDs
- expected ports
- whether each port is listening on `127.0.0.1`
- whether each sibling SQLite database exists
- tables in each SQLite database
- table row counts
- latest `created_at` activity where available

It writes:

- `memory/egg_state.db`
- `supervisor_scans`

It does not:

- clean files
- prune Docker
- reclaim WSL memory
- heal WSL distros
- delete temp files

### Endpoints

- `GET /`
- `GET /guardian.html`
- `GET /health`
- `GET /api/guardian/status`

### Verification

All Guardian runtime eggs compile and test:

- `system-guardian-alerts-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-docker-v1/runtime`: `go test ./...` passes
- `system-guardian-health-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-perf-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-security-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-supervisor-v1/runtime`: `go test ./...` passes
- `system-guardian-wsl-v1/runtime`: `go test ./...` passes

### Remaining Upgrade Work

- Add cooldown policy so repeated alerts/actions cannot spam the machine.
- Add richer action metadata shared by cleanup-capable eggs: risk, admin requirement, planned paths, estimated freed bytes, execution cooldown, and last result.
- Add a launch routine that starts the Guardian set in dependency order.
- Add a safe action review queue so cleanup requests can be approved after audit instead of executing directly.

## 2026-05-23 Follow-Up Repair Pass: Retention And Alert Tests

### Files Changed

- `eggs/system-guardian-alerts-v1/runtime/db.go`
- `eggs/system-guardian-alerts-v1/runtime/alerter_test.go`
- `eggs/system-guardian-docker-v1/runtime/db.go`
- `eggs/system-guardian-wsl-v1/runtime/db.go`
- `eggs/system-guardian-supervisor-v1/runtime/db.go`

### Repairs Applied

| Problem | Root Cause | Fix | Prevention Rule |
|---|---|---|---|
| SQLite logs could grow forever | Insert paths had no retention policy | Added bounded retention to alerts, Docker disk/prune logs, WSL distro/VHD/heal logs, and supervisor scans | Every recurring scan log needs a retention cap |
| Alert behavior had no tests | Alerts egg initially had no test files | Added tests for Telegram-not-configured and severity routing | Alert routing should be regression tested |

### Retention Caps

- `alerts_sent`: keeps newest 500 rows
- `docker_disk_state`: keeps newest 1000 rows
- `prune_history`: keeps newest 1000 rows
- `wsl_distros`: keeps newest 1000 rows
- `vhd_snapshots`: keeps newest 1000 rows
- `heal_ops`: keeps newest 1000 rows
- `supervisor_scans`: keeps newest 1000 rows

### Verification

All Guardian runtime eggs compile and test:

- `system-guardian-alerts-v1/runtime`: `go test ./...` passes
- `system-guardian-docker-v1/runtime`: `go test ./...` passes
- `system-guardian-health-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-network-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-perf-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-security-v1/runtime`: `go test ./...` passes, no test files
- `system-guardian-supervisor-v1/runtime`: `go test ./...` passes
- `system-guardian-wsl-v1/runtime`: `go test ./...` passes
