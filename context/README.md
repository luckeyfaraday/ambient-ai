# Ambient Context

Runtime reducers write local context here.

- `hot.json`: generated machine-readable compact context.
- `recent.md`: generated human-readable recent context.
- `hermes-handoff.md`: generated Hermes-readable handoff prompt.
- `learning/preferences.md`: explicit preferences and standing policy.
- `learning/trigger-outcomes.jsonl`: append-only outcome history.

The `sample-*` files show the expected shape without depending on runtime state.
