from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AmbientPaths:
    root: Path
    data_dir: Path
    context_dir: Path
    learning_dir: Path
    prompts_dir: Path
    db_path: Path

    @classmethod
    def from_env(cls, root: Path | None = None) -> "AmbientPaths":
        resolved_root = Path(os.environ.get("AMBIENT_AI_HOME") or root or Path.cwd()).resolve()
        return cls(
            root=resolved_root,
            data_dir=resolved_root / "data",
            context_dir=resolved_root / "context",
            learning_dir=resolved_root / "context" / "learning",
            prompts_dir=resolved_root / "prompts",
            db_path=resolved_root / "data" / "ambient.sqlite3",
        )

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.learning_dir.mkdir(parents=True, exist_ok=True)

