"""Prints a bcrypt hash for GATEWAY_PASSWORD_HASH.

    python -m gateway.hash_password

Reads the password from a prompt that does not echo and never writes it
anywhere - the point of the exercise is that the plaintext exists only in the
operator's head and in this process's memory for a moment.
"""

import getpass

import bcrypt

from gateway.auth import PASSWORD_HASH_ENV


def main() -> int:
    password = getpass.getpass("Super User password: ")
    if not password:
        print("Empty password; nothing generated.")
        return 1
    if password != getpass.getpass("Repeat: "):
        print("Passwords do not match; nothing generated.")
        return 1

    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    print(f"\n{PASSWORD_HASH_ENV}={digest}\n")
    print("Set that in the environment of the Gateway process (a .env file is read).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
