"""``.env`` loading: the README tells operators to configure RepoMate from a
``.env`` file, so something has to actually read it.

The contract these tests pin:

- a ``.env`` file is loaded into ``os.environ``
- the real environment always wins (no silent override of exports)
- ``REPOMATE_SKIP_DOTENV=1`` disables loading (the hermetic suite sets it)
- malformed lines are skipped, never fatal
- the loaded path is reported so ``/api/health`` can explain a heuristic run
"""

from __future__ import annotations

import os

import pytest

from repomate_core.env import (
    ENV_FILE_VAR,
    SKIP_ENV_VAR,
    load_env_file,
    loaded_env_file,
)


@pytest.fixture(autouse=True)
def _allow_loading(monkeypatch):
    """The global suite disables dotenv; these tests exercise it.

    ``load_env_file`` writes straight into ``os.environ`` (that is its job),
    so the whole environment is snapshotted and restored around each test —
    otherwise values loaded here would leak into unrelated test modules.
    """
    snapshot = dict(os.environ)
    monkeypatch.delenv(SKIP_ENV_VAR, raising=False)
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    for key in ("OLLAMA_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL"):
        monkeypatch.delenv(key, raising=False)
    # ``loaded_env_file()`` reports module state; reset it per test too.
    import repomate_core.env as env_module

    monkeypatch.setattr(env_module, "_loaded_path", None, raising=False)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


def _write_env(tmp_path, text: str):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_values_into_environment(tmp_path, monkeypatch):
    path = _write_env(
        tmp_path,
        "OLLAMA_API_KEY=sk-from-file\n"
        "OLLAMA_BASE_URL=https://gateway.test/v1\n"
        "OLLAMA_MODEL=gemma4:31b\n",
    )
    loaded = load_env_file(path)

    assert loaded == path
    assert os.environ["OLLAMA_API_KEY"] == "sk-from-file"
    assert os.environ["OLLAMA_BASE_URL"] == "https://gateway.test/v1"
    assert loaded_env_file() == str(path)


def test_real_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-from-shell")
    path = _write_env(tmp_path, "OLLAMA_API_KEY=sk-from-file\n")

    load_env_file(path)

    assert os.environ["OLLAMA_API_KEY"] == "sk-from-shell"


def test_empty_exported_value_is_respected(tmp_path, monkeypatch):
    # The test suite pins the heuristic planner by exporting an *empty* key;
    # the file must not resurrect it.
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    path = _write_env(tmp_path, "OLLAMA_API_KEY=sk-from-file\n")

    load_env_file(path)

    assert os.environ["OLLAMA_API_KEY"] == ""


def test_override_flag_replaces_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "shell-model")
    path = _write_env(tmp_path, "OLLAMA_MODEL=file-model\n")

    load_env_file(path, override=True)

    assert os.environ["OLLAMA_MODEL"] == "file-model"


def test_skip_flag_disables_loading(tmp_path, monkeypatch):
    monkeypatch.setenv(SKIP_ENV_VAR, "1")
    path = _write_env(tmp_path, "OLLAMA_API_KEY=sk-from-file\n")

    assert load_env_file(path) is None
    assert "OLLAMA_API_KEY" not in os.environ


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "nope.env") is None


def test_parses_comments_quotes_and_export(tmp_path, monkeypatch):
    path = _write_env(
        tmp_path,
        "# a comment\n"
        "\n"
        "export OLLAMA_MODEL=\"quoted model\"\n"
        "OLLAMA_BASE_URL='https://single.test/v1'\n"
        "not-a-pair\n"
        "=novalue\n"
        "OLLAMA_API_KEY=sk-ok\n",
    )

    load_env_file(path)

    assert os.environ["OLLAMA_MODEL"] == "quoted model"
    assert os.environ["OLLAMA_BASE_URL"] == "https://single.test/v1"
    assert os.environ["OLLAMA_API_KEY"] == "sk-ok"


def test_env_file_var_points_at_an_alternate_path(tmp_path, monkeypatch):
    path = _write_env(tmp_path, "OLLAMA_MODEL=from-alt\n")
    monkeypatch.setenv(ENV_FILE_VAR, str(path))

    load_env_file()

    assert os.environ["OLLAMA_MODEL"] == "from-alt"


def test_loading_makes_the_model_planner_available(tmp_path, monkeypatch):
    """The end-to-end point of the fix: a ``.env`` key turns the model
    planner on instead of silently falling back to the heuristic one."""
    from repomate_core.models.openai import provider_from_env
    from repomate_core.orchestration.pipeline import resolve_planner

    assert resolve_planner().name == "heuristic-v1"

    _write_env(
        tmp_path,
        "OLLAMA_API_KEY=sk-live\nOLLAMA_BASE_URL=https://gateway.test/v1\n",
    )
    load_env_file(tmp_path / ".env")

    provider = provider_from_env()
    assert provider is not None
    assert resolve_planner().name.startswith("model:")
