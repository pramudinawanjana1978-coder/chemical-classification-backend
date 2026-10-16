"""
Generate the values for your backend .env file.

    python make_admin_hash.py

It asks for the admin password (typing is hidden), then prints
ADMIN_PASSWORD_HASH and a random ADMIN_SECRET_KEY. Copy them into .env.
The plain-text password is never saved anywhere.
"""

import getpass
import secrets

from werkzeug.security import generate_password_hash


def main():
    password = getpass.getpass("Choose an admin password (min 10 characters): ")
    if len(password) < 10:
        raise SystemExit("Password too short. Use at least 10 characters.")
    if getpass.getpass("Repeat password: ") != password:
        raise SystemExit("Passwords do not match.")

    print("\nAdd these lines to backend/.env (keep the single quotes):\n")
    print("ADMIN_USERNAME=admin")
    print(f"ADMIN_PASSWORD_HASH='{generate_password_hash(password)}'")
    print(f"ADMIN_SECRET_KEY={secrets.token_hex(32)}")


if __name__ == "__main__":
    main()
