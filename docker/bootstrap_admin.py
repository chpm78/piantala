from __future__ import annotations

import os
from datetime import UTC, datetime

from piantala import create_app
from piantala.extensions import db
from piantala.models import Role, User


def main() -> None:
    """Create the initial admin user from Docker environment variables."""
    username = os.getenv("PIANTALA_ADMIN_USERNAME", "").strip()
    email = os.getenv("PIANTALA_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("PIANTALA_ADMIN_PASSWORD", "").strip()

    if not (username and password):
        return

    app = create_app()
    with app.app_context():
        existing_user = User.query.filter(User.username == username).first()
        if existing_user is None and email:
            existing_user = User.query.filter(User.email == email).first()
        if existing_user is not None:
            if email and not existing_user.email:
                existing_user.email = email
            if existing_user.email and existing_user.email_confirmed_at is None:
                existing_user.email_confirmed_at = datetime.now(UTC)
                db.session.commit()
            return

        admin_role = Role.query.filter_by(name="admin").first()
        if admin_role is None:
            return

        user = User(
            username=username,
            email=email or None,
            is_active=True,
            email_confirmed_at=datetime.now(UTC) if email else None,
        )
        user.set_password(password)
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()


if __name__ == "__main__":
    main()
