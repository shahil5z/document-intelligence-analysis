import os
import re
import stat
from pathlib import Path

import pytest

from scripts.generate_env import (
    GENERATED_KEYS,
    EnvGenerationError,
    generate,
    main,
    merge,
    missing_keys,
    read_key_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = PROJECT_ROOT / ".env.example"
FAKE_KEY = "fake-openai-key-for-tests-0123456789"


def _parse(path: Path) -> dict[str, str]:
    pairs = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key] = value
    return pairs


def test_generates_random_url_safe_secrets(tmp_path: Path) -> None:
    out = tmp_path / ".env"
    applied = generate(example=EXAMPLE, output=out, force=False)
    assert set(applied) == set(GENERATED_KEYS)
    values = _parse(out)
    for key in GENERATED_KEYS:
        assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", values[key]), key
        assert not values[key].startswith("replace-with")
    assert values["OPENAI_API_KEY"] == "replace-with-your-openai-api-key"
    # Every other line of the template is preserved.
    assert set(values) == set(_parse(EXAMPLE))
    if os.name == "posix":  # Windows has no POSIX permission bits (see README, Windows notes)
        assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_two_runs_produce_different_secrets(tmp_path: Path) -> None:
    first, second = tmp_path / "a.env", tmp_path / "b.env"
    generate(example=EXAMPLE, output=first, force=False)
    generate(example=EXAMPLE, output=second, force=False)
    assert _parse(first)["JWT_SECRET_KEY"] != _parse(second)["JWT_SECRET_KEY"]


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / ".env"
    out.write_text("KEEP=me\n")
    with pytest.raises(EnvGenerationError, match="--force"):
        generate(example=EXAMPLE, output=out, force=False)
    assert out.read_text() == "KEEP=me\n"
    generate(example=EXAMPLE, output=out, force=True)
    assert "JWT_SECRET_KEY" in _parse(out)


@pytest.mark.parametrize(
    "content",
    [f"OPENAI_API_KEY={FAKE_KEY}\n", f'export OPENAI_API_KEY="{FAKE_KEY}"\n', f"{FAKE_KEY}\n"],
)
def test_imports_openai_key_from_file(tmp_path: Path, content: str) -> None:
    key_file = tmp_path / "env"
    key_file.write_text(content)
    assert read_key_file(key_file) == FAKE_KEY
    out = tmp_path / ".env"
    applied = generate(example=EXAMPLE, output=out, force=False, openai_key_file=key_file)
    assert "OPENAI_API_KEY" in applied
    assert _parse(out)["OPENAI_API_KEY"] == FAKE_KEY


def test_imports_openai_key_from_environment(tmp_path: Path) -> None:
    out = tmp_path / ".env"
    generate(
        example=EXAMPLE,
        output=out,
        force=False,
        openai_key_env="MY_KEY",
        environ={"MY_KEY": FAKE_KEY},
    )
    assert _parse(out)["OPENAI_API_KEY"] == FAKE_KEY
    with pytest.raises(EnvGenerationError, match="MY_KEY is not set"):
        generate(example=EXAMPLE, output=out, force=True, openai_key_env="MY_KEY", environ={})


def test_unrecognised_key_file_is_rejected(tmp_path: Path) -> None:
    key_file = tmp_path / "env"
    key_file.write_text("SOMETHING=else\nOTHER=value\n")
    with pytest.raises(EnvGenerationError) as excinfo:
        read_key_file(key_file)
    assert "else" not in str(excinfo.value)


def test_cli_never_prints_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key_file = tmp_path / "env"
    key_file.write_text(f"OPENAI_API_KEY={FAKE_KEY}\n")
    out = tmp_path / ".env"
    code = main(
        ["--example", str(EXAMPLE), "--output", str(out), "--openai-key-file", str(key_file)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "set JWT_SECRET_KEY" in printed
    assert "set OPENAI_API_KEY" in printed
    for value in _parse(out).values():
        if len(value) >= 20 and not value.startswith(("replace-with", "application/")):
            assert value not in printed
    assert main(["--example", str(EXAMPLE), "--output", str(out)]) == 1


# --- --merge -------------------------------------------------------------------------

# The key set of the user's existing (DIP1-era) .env, values replaced by test values.
DIP1_KEYS = [
    "APP_NAME",
    "APP_ENV",
    "DEBUG",
    "LOG_LEVEL",
    "API_PORT",
    "JWT_SECRET_KEY",
    "JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
    "STORAGE_BACKEND",
    "STORAGE_PATH",
    "MAX_UPLOAD_SIZE_BYTES",
    "ALLOWED_EXTENSIONS",
    "ALLOWED_CONTENT_TYPES",
    "CORS_ALLOWED_ORIGINS",
    "OPENAI_API_KEY",
]


def _template_keys() -> list[str]:
    return [
        line.split("=", 1)[0]
        for line in EXAMPLE.read_text().splitlines()
        if re.match(r"^[A-Z][A-Z0-9_]*=", line)
    ]


def _existing_env(
    path: Path, newline: str = "\n", keys: tuple[str, ...] | list[str] = DIP1_KEYS
) -> bytes:
    """A user's .env: template defaults for ``keys``, real-looking secrets and API key."""
    defaults = _parse(EXAMPLE)
    lines = ["# my local settings"]
    for key in keys:
        value = defaults[key]
        if key in GENERATED_KEYS:
            value = f"existing-secret-{key.lower().replace('_', '-')}-0123456789abcdef"
        elif key == "OPENAI_API_KEY":
            value = FAKE_KEY
        lines.append(f"{key}={value}")
    data = (newline.join(lines) + newline).encode()
    path.write_bytes(data)
    return data


def test_merge_appends_only_missing_keys_and_keeps_existing_bytes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    original = _existing_env(env)
    expected_missing = [key for key in _template_keys() if key not in DIP1_KEYS]
    assert expected_missing  # DIP2/DIP3 added settings
    assert missing_keys(example=EXAMPLE, output=env) == expected_missing

    added = merge(example=EXAMPLE, output=env, openai_key_file=None)
    assert added == expected_missing
    merged = env.read_bytes()
    assert merged.startswith(original)  # every existing line and value untouched
    values = _parse(env)
    for key in DIP1_KEYS:
        assert values[key] == _parse_bytes(original)[key]
    for key in expected_missing:
        assert key in values
    assert (tmp_path / ".env.bak").read_bytes() == original
    # Idempotent: nothing left to add, file unchanged.
    assert merge(example=EXAMPLE, output=env) == []
    assert env.read_bytes() == merged


def _parse_bytes(data: bytes) -> dict[str, str]:
    pairs = {}
    for line in data.decode().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key] = value
    return pairs


def test_merge_generates_missing_secrets_and_never_overwrites_openai_key(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    keys = [k for k in DIP1_KEYS if k not in {"REDIS_PASSWORD", "OPENAI_API_KEY"}]
    _existing_env(env, keys=keys)
    key_file = tmp_path / "env"
    key_file.write_text("OPENAI_API_KEY=" + FAKE_KEY + "-from-file\n")
    added = merge(example=EXAMPLE, output=env, openai_key_file=key_file, backup=False)
    values = _parse(env)
    assert "REDIS_PASSWORD" in added
    assert re.fullmatch(r"[A-Za-z0-9_-]{40,}", values["REDIS_PASSWORD"])
    assert values["OPENAI_API_KEY"] == FAKE_KEY + "-from-file"
    assert not (tmp_path / ".env.bak").exists()

    # Present key: --openai-key-file does not replace it.
    other = tmp_path / "other.env"
    _existing_env(other)
    merge(example=EXAMPLE, output=other, openai_key_file=key_file)
    assert _parse(other)["OPENAI_API_KEY"] == FAKE_KEY


def test_merge_preserves_windows_line_endings(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    original = _existing_env(env, newline="\r\n")
    merge(example=EXAMPLE, output=env)
    merged = env.read_bytes()
    assert merged.startswith(original)
    assert b"\n" not in merged.replace(b"\r\n", b"")


def test_merged_file_is_loadable_settings(tmp_path: Path) -> None:
    from app.core.config import load_settings  # noqa: PLC0415

    env = tmp_path / ".env"
    _existing_env(env)
    merge(example=EXAMPLE, output=env)
    settings = load_settings(_env_file=str(env), app_env="development")
    assert settings.chunk_size == 400
    assert settings.embedding_dimension == 384


def test_merge_requires_an_existing_file(tmp_path: Path) -> None:
    with pytest.raises(EnvGenerationError, match="does not exist"):
        merge(example=EXAMPLE, output=tmp_path / ".env")


def test_merge_cli_dry_run_lists_names_only_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    original = _existing_env(env)
    args = ["--example", str(EXAMPLE), "--output", str(env), "--merge"]
    assert main([*args, "--dry-run"]) == 0
    dry = capsys.readouterr().out
    assert "missing RATE_LIMIT_BACKEND" in dry
    assert env.read_bytes() == original

    assert main(args) == 0
    out = capsys.readouterr().out
    assert "added EMBEDDING_MODEL" in out
    for value in _parse(env).values():
        if len(value) >= 12 and value not in {"development", "localhost"}:
            assert value not in out
    assert main(args) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_dry_run_requires_merge(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--dry-run"])
    capsys.readouterr()
