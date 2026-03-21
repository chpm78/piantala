from __future__ import annotations

import os

from piantala import create_app
from piantala.extensions import db
from piantala.models import Role, User


def main() -> None:
    username = os.getenv("PIANTALA_ADMIN_USERNAME", "").strip()
    email = os.getenv("PIANTALA_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("PIANTALA_ADMIN_PASSWORD", "").strip()

    if not (username and email and password):
        return

    app = create_app()
    with app.app_context():
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing_user is not None:
            return

        admin_role = Role.query.filter_by(name="admin").first()
        if admin_role is None:
            return

        user = User(username=username, email=email, is_active=True)
        user.set_password(password)
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()


if __name__ == "__main__":
    main()
