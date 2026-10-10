"""One-time creation of the first administrator:  python -m app.auth.bootstrap --email you@company.org --name "Your Name"
The password is read from the console (not echoed) and stored only as an argon2id hash. Refused when an administrator already exists."""
from __future__ import annotations

import argparse
import getpass
import sys

from .service import AuthError, bootstrap_admin


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    p1 = getpass.getpass("Password (12+ characters): ")
    if p1 != getpass.getpass("Repeat the password: "):
        print("The passwords differ.")
        return 1
    try:
        uid = bootstrap_admin(a.email, a.name, p1)
    except AuthError as e:
        print(e.message)
        return 1
    print(f"Administrator created ({uid}). Sign in with this email and password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
