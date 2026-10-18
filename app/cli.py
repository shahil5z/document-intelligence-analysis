"""Operational commands.

Usage::

    python -m app.cli create-admin --email admin@example.com
    python -m app.cli reconcile-stale-jobs

The password is read from the ADMIN_PASSWORD environment variable or prompted for
interactively; it is never accepted as a command-line argument (shell history).
"""

import argparse
import getpass
import os
import sys

from app.core.config import get_settings
from app.core.security import PasswordHasher
from app.db.repositories.users import UserRepository
from app.db.session import get_session_factory, session_scope
from app.domain.enums import UserRole
from app.schemas.auth import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.services.auth_service import normalize_email


def create_admin(email: str, password: str) -> str:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise SystemExit(
            f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long"
        )
    email = normalize_email(email)
    with session_scope() as session:
        users = UserRepository(session)
        existing = users.get_by_email(email)
        if existing is not None:
            existing.role = UserRole.ADMIN
            session.commit()
            return f"Promoted existing user {existing.id} to admin"
        user = users.add(
            email=email, password_hash=PasswordHasher().hash(password), role=UserRole.ADMIN
        )
        session.commit()
        return f"Created admin user {user.id}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create an admin user or promote an existing one")
    admin.add_argument("--email", required=True)
    sub.add_parser(
        "reconcile-stale-jobs",
        help="Fail jobs stuck in processing/retrying longer than STALE_JOB_TIMEOUT_SECONDS",
    )
    args = parser.parse_args(argv)

    if args.command == "create-admin":
        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
        print(create_admin(args.email, password))
    elif args.command == "reconcile-stale-jobs":
        from app.workers.reconcile import reconcile_stale_jobs  # noqa: PLC0415

        failed = reconcile_stale_jobs(
            get_session_factory(), timeout_seconds=get_settings().stale_job_timeout_seconds
        )
        print(f"Marked {failed} stale job(s) as failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
