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
