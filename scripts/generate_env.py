"""Create a local .env from .env.example with freshly generated secrets.

Usage (from the repository root):

    python scripts/generate_env.py
    python scripts/generate_env.py --openai-key-file env          # import OPENAI_API_KEY
    python scripts/generate_env.py --openai-key-env OPENAI_API_KEY # ...or from a variable
    python scripts/generate_env.py --force                         # overwrite existing .env

JWT_SECRET_KEY, POSTGRES_PASSWORD and REDIS_PASSWORD get ``secrets.token_urlsafe``
values (URL-safe, so they work unescaped inside connection URLs). Values are never
printed; only the names of the keys that were set. Standard library only.
"""

import argparse
import os
import re
import secrets
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

GENERATED_KEYS: dict[str, int] = {
    "JWT_SECRET_KEY": 48,
    "POSTGRES_PASSWORD": 32,
    "REDIS_PASSWORD": 32,
}
OPENAI_KEY = "OPENAI_API_KEY"
_ASSIGNMENT = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")


class EnvGenerationError(Exception):
    """Raised for user-facing problems; messages never contain secret values."""


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_key_file(path: Path) -> str:
    """Read an OpenAI key from a file containing either ``OPENAI_API_KEY=...`` or the bare key."""
    if not path.is_file():
        raise EnvGenerationError(f"Key file not found: {path}")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for line in lines:
        candidate = line.removeprefix("export ").strip()
        match = _ASSIGNMENT.match(candidate)
        if match and match.group("key") == OPENAI_KEY:
            return _validate_key(_strip_quotes(match.group("value")), source=str(path))
    if len(lines) == 1 and "=" not in lines[0]:
        return _validate_key(_strip_quotes(lines[0]), source=str(path))
    raise EnvGenerationError(
        f"{path} must contain a line 'OPENAI_API_KEY=...' or only the key itself"
    )


def _validate_key(value: str, *, source: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        raise EnvGenerationError(f"The OpenAI key from {source} is empty or contains whitespace")
    return value


def render_env(template: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Replace ``KEY=...`` lines for the given keys; return (content, keys actually set)."""
    output: list[str] = []
    applied: list[str] = []
    for line in template.splitlines():
        match = _ASSIGNMENT.match(line)
        if match and match.group("key") in values:
            key = match.group("key")
            output.append(f"{key}={values[key]}")
            applied.append(key)
        else:
            output.append(line)
    missing = sorted(set(values) - set(applied))
    if missing:
        raise EnvGenerationError(f"Template has no line for: {', '.join(missing)}")
    return "\n".join(output) + "\n", applied


def _write_private(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.replace(tmp, path)
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def generate(
    *,
    example: Path,
    output: Path,
    force: bool,
    openai_key_file: Path | None = None,
    openai_key_env: str | None = None,
    environ: dict[str, str] | None = None,
) -> list[str]:
    if output.exists() and not force:
        raise EnvGenerationError(f"{output} already exists; use --force to overwrite it")
    if not example.is_file():
        raise EnvGenerationError(f"Template not found: {example}")

    values = {key: secrets.token_urlsafe(nbytes) for key, nbytes in GENERATED_KEYS.items()}
    if openai_key_file is not None:
        values[OPENAI_KEY] = read_key_file(openai_key_file)
    elif openai_key_env is not None:
        env = os.environ if environ is None else environ
        value = env.get(openai_key_env, "")
        if not value:
            raise EnvGenerationError(f"Environment variable {openai_key_env} is not set")
        values[OPENAI_KEY] = _validate_key(value.strip(), source=f"${openai_key_env}")

    content, applied = render_env(example.read_text(encoding="utf-8"), values)
    _write_private(output, content)
    return applied


def main(argv: Sequence[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--example", type=Path, default=root / ".env.example")
    parser.add_argument("--output", type=Path, default=root / ".env")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--openai-key-file", type=Path, help="file with OPENAI_API_KEY=... or the bare key"
    )
    source.add_argument("--openai-key-env", help="name of an environment variable holding the key")
    args = parser.parse_args(argv)

    try:
        applied = generate(
            example=args.example,
            output=args.output,
            force=args.force,
            openai_key_file=args.openai_key_file,
            openai_key_env=args.openai_key_env,
        )
    except EnvGenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    for key in applied:
        print(f"  set {key}")
    if OPENAI_KEY not in applied:
        print(f"  {OPENAI_KEY} left as placeholder (optional in DIP1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
