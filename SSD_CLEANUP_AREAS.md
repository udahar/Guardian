# Guardian SSD Cleanup Areas

This is the shortlist Guardian should use when `C:` gets tight.

## Safe First Pass

These are usually safe to clean without deleting project data:

- `C:\Users\Richard\AppData\Local\pip\cache`
  Command: `python -m pip cache purge`
- `C:\Users\Richard\AppData\Local\npm-cache`
  Command: `npm cache clean --force`
- `C:\Users\Richard\AppData\Local\pnpm\store`
  Command: `pnpm store prune`
- `C:\Users\Richard\.gradle\caches`
  Command: remove caches or let Gradle rebuild them
- `C:\Users\Richard\AppData\Local\Temp`
  Command: Guardian Windows cleanup
- Recycle Bin
  Command: `Clear-RecycleBin -Force`
- Python `__pycache__`, `.pytest_cache`, `.tsbuildinfo`, `.next`, `dist`, `build`, `target`
  Command: use project-specific clean/rebuild flows

## Manual Review

These can free a lot of space, but should be reviewed before removal:

- `C:\Users\Richard\Downloads`
- old zip archives, installers, and one-off exports
- dormant project `node_modules` folders
- duplicate local Ollama models you no longer use

## High-Impact But Not Safe By Default

These are large on this machine, but they contain live data or installed models:

- `C:\Users\Richard\.ollama\models`
  Use `ollama list` and `ollama rm <model>` for anything you no longer need.
- `C:\Users\Richard\clawd\services\qdrant\storage`
  Vector database data. Do not delete blindly.
- `C:\Users\Richard\clawd\storage\collections`
  Local collection data. Review collection owners before removal.

## Current Findings On This Machine

Snapshot from 2026-03-26:

- `C:\Users\Richard\.ollama` about `42 GB`
- `C:\Users\Richard\Downloads` about `10.4 GB`
- `C:\Users\Richard\clawd\services\qdrant` about `12.0 GB`
- `C:\Users\Richard\clawd\storage\collections` about `4.45 GB`
- `C:\Users\Richard\clawd\services` about `13.1 GB`
- `C:\Users\Richard\clawd\Prime` about `8.5 GB`

## Guardian Notes

- Guardian launcher was updated to use the current `Guardian.modules.*` package layout.
- The launcher now sets `PYTHONPATH` to the repo root so module commands can run.
- `launcher.ps1 ollama` is now usable again for checking duplicate Ollama processes.
- Disk report and cache scans are still expensive on a very full drive; use them when you can wait for a full scan.
