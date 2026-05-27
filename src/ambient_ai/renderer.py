from __future__ import annotations

from pathlib import Path

from .paths import AmbientPaths


def render_hermes_prompt(paths: AmbientPaths) -> str:
    template = default_template()
    template_path = paths.prompts_dir / "hermes_handoff.md.tmpl"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    return template.format(
        root=paths.root,
        hot_json=paths.context_dir / "hot.json",
        recent_md=paths.context_dir / "recent.md",
        preferences_md=paths.learning_dir / "preferences.md",
        outcomes_jsonl=paths.learning_dir / "trigger-outcomes.jsonl",
        agent_contract=paths.prompts_dir / "agent_work_contract.md",
    )


def write_hermes_prompt(paths: AmbientPaths, output: Path | None = None) -> Path:
    paths.ensure()
    prompt = render_hermes_prompt(paths)
    output_path = output or paths.context_dir / "hermes-handoff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt, encoding="utf-8")
    return output_path


def default_template() -> str:
    return """# Ambient AI Hermes Handoff

Workspace: {root}

You are Hermes, an external agent runtime reading an Ambient AI context handoff.

Read:
- Hot context: {hot_json}
- Recent context: {recent_md}
- Preferences: {preferences_md}
- Trigger outcomes: {outcomes_jsonl}
- Agent work contract: {agent_contract}

Decide whether useful autonomous work exists. If not, no-op silently.
"""
