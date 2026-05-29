from __future__ import annotations

from ambient_ai.paths import AmbientPaths


def test_explicit_root_overrides_environment(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit"
    env_root = tmp_path / "env"
    monkeypatch.setenv("AMBIENT_AI_HOME", str(env_root))

    paths = AmbientPaths.from_env(explicit)

    assert paths.root == explicit.resolve()
