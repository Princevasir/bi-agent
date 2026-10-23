import getpass
import sys

from app.appdb import create_user, get_user
from app.auth import hash_password
from app.db import DBError

ROLES = ("analyst", "limited")
OPTIONS = {"--password-stdin", "--exist-ok"}   # for scripts/setup.sh (demo gap D4)
USAGE = "usage: python -m app.cli create-user <username> <analyst|limited> [--password-stdin] [--exist-ok]"


def main(argv):
    options = set(argv[4:])
    if len(argv) < 4 or argv[1] != "create-user" or argv[3] not in ROLES or not options <= OPTIONS:
        print(USAGE)
        return 2
    name, role = argv[2], argv[3]
    if "--exist-ok" in options and get_user(name) is not None:
        print(f"{name.lower()} already exists; left unchanged.")
        return 0
    if "--password-stdin" in options:
        password = sys.stdin.readline().rstrip("\n")
        confirmed = True
    else:
        password = getpass.getpass("Password (at least 12 characters): ")
        confirmed = password == getpass.getpass("Repeat password: ")
    if len(password) < 12 or not confirmed:
        print("Passwords must match and be at least 12 characters.")
        return 1
    try:
        create_user(name, hash_password(password), role)
    except DBError:
        print("Could not create the user. Does the username already exist?")
        return 1
    print(f"Created {name.lower()} ({role}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
