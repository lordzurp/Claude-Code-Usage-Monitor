# Brief consultant — contexte de la review

**Date** : 2026-03-28

## Ce qui a changé depuis ton étude

Ton étude (etude-monitor-multi-agent.md) proposait une refonte significative :
virer le TUI, partition per-agent, FleetBudget, agrégations multi-axes.

Décision architecturale : on réduit à une modif mineure.

### Ce qu'on garde de ton étude
- §3.1 : multi-home reader (scanner N répertoires au lieu d'un)

### Ce qu'on ne fait PAS (pour l'instant)
- §3.3 : partition par agent (pas de tag agent_id dans UsageEntry)
- §3.4 : agrégations multi-axes
- §3.5 : burn rate per-agent
- §3.7 : FleetBudget / strategy
- Le TUI est CONSERVÉ — c'est le livrable principal (dashboard live tmux)

### Pourquoi
Le besoin immédiat est de surveiller la conso fleet consolidée (va-t-on
taper les quotas ?), pas de savoir quel agent consomme quoi. Le tracking
per-agent viendra via ccusage (reporting hebdo, backlog v8).

## Ce que tu dois vérifier

Le code, pas la stratégie. Les décisions ci-dessus sont prises.

Ton job : est-ce que l'implémentation multi-path est correcte, robuste,
rétrocompatible, et prête pour un PR upstream sur un repo MIT tiers ?

Détails dans work/review-request.md.
