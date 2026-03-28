# Plan : Multi-home support

**Date** : 2026-03-28
**Statut** : doing

## Objectif

Permettre à claude-monitor de scanner les JSONL de plusieurs homes Claude Code
simultanément, pour agrégation consolidée dans le dashboard TUI existant.

## Fichiers à modifier

1. `src/claude_monitor/core/settings.py` — ajouter `data_paths: Optional[List[str]]`
2. `src/claude_monitor/data/reader.py` — `load_usage_entries` accepte liste de paths
3. `src/claude_monitor/data/analysis.py` — relayer data_paths
4. `src/claude_monitor/monitoring/data_manager.py` — pass-through data_paths
5. `src/claude_monitor/monitoring/orchestrator.py` — pass-through data_paths
6. `src/claude_monitor/cli/main.py` — passer toute la liste, pas [0]

## Vérification

python -m pytest src/tests/
