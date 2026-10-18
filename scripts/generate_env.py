"""Create a local .env from .env.example with freshly generated secrets.

Usage (from the repository root):

    python scripts/generate_env.py
    python scripts/generate_env.py --openai-key-file env          # import OPENAI_API_KEY
    python scripts/generate_env.py --openai-key-env OPENAI_API_KEY # ...or from a variable
    python scripts/generate_env.py --force                         # overwrite existing .env
    python scripts/generate_env.py --merge --dry-run               # list keys missing in .env
    python scripts/generate_env.py --merge                         # append the missing keys

JWT_SECRET_KEY, POSTGRES_PASSWORD and REDIS_PASSWORD get ``secrets.token_urlsafe``
values (URL-safe, so they work unescaped inside connection URLs). Values are never
printed; only the names of the keys that were set. Standard library only.

``--merge`` keeps an existing .env byte-for-byte (every existing line and value stays
as it is) and appends only the keys that .env.example defines but .env lacks, each
with the comment lines that precede it in the template and the template's default.
A missing secret (JWT_SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD) is generated
instead of copying the placeholder; OPENAI_API_KEY is only added from
--openai-key-file/--openai-key-env (otherwise as the placeholder). The original file
is kept as .env.bak unless --no-backup is given.
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


def _assigned_keys(content: str) -> set[str]:
    keys: set[str] = set()
    for line in content.splitlines():
        candidate = line.strip().removeprefix("export ").strip()
        match = _ASSIGNMENT.match(candidate)
        if match:
            keys.add(match.group("key"))
    return keys


def _template_entries(template: str) -> list[tuple[str, list[str], str]]:
    """``(key, preceding comment lines, assignment line)`` for each active template key."""
    entries: list[tuple[str, list[str], str]] = []
    comments: list[str] = []
    for line in template.splitlines():
        stripped = line.strip()
        match = _ASSIGNMENT.match(stripped)
        if match:
            entries.append((match.group("key"), comments, stripped))
            comments = []
        elif stripped.startswith("#"):
            comments.append(stripped)
        else:
            comments = []
    return entries


def missing_keys(*, example: Path, output: Path) -> list[str]:
    """Names of template keys that the existing env file does not assign."""
    if not output.is_file():
        raise EnvGenerationError(f"{output} does not exist; run without --merge to create it")
    if not example.is_file():
        raise EnvGenerationError(f"Template not found: {example}")
    present = _assigned_keys(output.read_text(encoding="utf-8-sig"))
    entries = _template_entries(example.read_text(encoding="utf-8"))
    return [key for key, _, _ in entries if key not in present]


def merge(
    *,
    example: Path,
    output: Path,
    openai_key_file: Path | None = None,
    openai_key_env: str | None = None,
    environ: dict[str, str] | None = None,
    backup: bool = True,
) -> list[str]:
    """Append template keys missing from ``output``; existing lines are never changed."""
    missing = missing_keys(example=example, output=output)
    if not missing:
        return []
    imported: str | None = None
    if OPENAI_KEY in missing:
        if openai_key_file is not None:
            imported = read_key_file(openai_key_file)
        elif openai_key_env is not None:
            env = os.environ if environ is None else environ
            value = env.get(openai_key_env, "").strip()
            if not value:
                raise EnvGenerationError(f"Environment variable {openai_key_env} is not set")
            imported = _validate_key(value, source=f"${openai_key_env}")

    raw = output.read_bytes()
    original = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in original else "\n"
    block: list[str] = ["", "# --- Added by scripts/generate_env.py --merge from .env.example ---"]
    for key, comments, line in _template_entries(example.read_text(encoding="utf-8")):
        if key not in missing:
            continue
        block.append("")
        block.extend(comments)
        if key in GENERATED_KEYS:
            block.append(f"{key}={secrets.token_urlsafe(GENERATED_KEYS[key])}")
        elif key == OPENAI_KEY and imported is not None:
            block.append(f"{key}={imported}")
        else:
            block.append(line)
    prefix = original if not original or original.endswith(("\n", "\r")) else original + newline
    if backup:
        _write_private(output.with_name(output.name + ".bak"), original)
    _write_private(output, prefix + newline.join(block if prefix else block[1:]) + newline)
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--example", type=Path, default=root / ".env.example")
    parser.add_argument("--output", type=Path, default=root / ".env")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="overwrite an existing output file")
    mode.add_argument(
        "--merge",
        action="store_true",
        help="append keys from the template that the existing output file lacks",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="with --merge: only list the missing key names"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="with --merge: do not write <output>.bak"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--openai-key-file", type=Path, help="file with OPENAI_API_KEY=... or the bare key"
    )
    source.add_argument("--openai-key-env", help="name of an environment variable holding the key")
    args = parser.parse_args(argv)
    if (args.dry_run or args.no_backup) and not args.merge:
        parser.error("--dry-run and --no-backup require --merge")

    if args.merge:
        return _run_merge(args)
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
        print(f"  {OPENAI_KEY} left as placeholder (only POST /ask needs it)")
    return 0


def _run_merge(args: argparse.Namespace) -> int:
    try:
        if args.dry_run:
            missing = missing_keys(example=args.example, output=args.output)
            added: list[str] = []
        else:
            missing = merge(
                example=args.example,
                output=args.output,
                openai_key_file=args.openai_key_file,
                openai_key_env=args.openai_key_env,
                backup=not args.no_backup,
            )
            added = missing
    except EnvGenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not missing:
        print(f"{args.output} already has every key from {args.example.name}; nothing to do")
        return 0
    verb = "missing" if args.dry_run else "added"
    print(f"{len(missing)} key(s) {verb} in {args.output} (existing values unchanged):")
    for key in missing:
        note = " (generated)" if key in GENERATED_KEYS and added else ""
        print(f"  {verb} {key}{note}")
    if added and not args.no_backup:
        print(f"Previous file kept as {args.output.name}.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
