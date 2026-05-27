from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], root: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["AMBIENT_AI_HOME"] = str(root)
    subprocess.run([sys.executable, "-m", "ambient_ai", *args], cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ambient-ai-smoke-") as tmp:
        root = Path(tmp)
        prompts = root / "prompts"
        prompts.mkdir()
        (prompts / "hermes_handoff.md.tmpl").write_text(
            (REPO_ROOT / "prompts" / "hermes_handoff.md.tmpl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        run(["init"], root)
        run(["ingest-sample"], root)
        run(["reduce"], root)
        run(["render-hermes"], root)

        expected = [
            root / "data" / "ambient.sqlite3",
            root / "context" / "hot.json",
            root / "context" / "recent.md",
            root / "context" / "hermes-handoff.md",
            root / "context" / "learning" / "preferences.md",
            root / "context" / "learning" / "trigger-outcomes.jsonl",
        ]
        missing = [path for path in expected if not path.exists()]
        if missing:
            raise AssertionError(f"Missing expected files: {missing}")

        prompt = (root / "context" / "hermes-handoff.md").read_text(encoding="utf-8")
        assert "external agent runtime" in prompt
        assert "Do not ask the user what to do by default" in prompt
        assert "No-op silently" in prompt
        assert "large downloads" in prompt

    print("Ambient AI smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
