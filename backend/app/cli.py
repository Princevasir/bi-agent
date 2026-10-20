import getpass
import sys

from app.appdb import create_user
from app.auth import hash_password
from app.db import DBError

ROLES = ("analyst", "limited")


def main(argv):
    if len(argv) != 4 or argv[1] != "create-user" or argv[3] not in ROLES:
        print("usage: python -m app.cli create-user <username> <analyst|limited>")
        return 2
    password = getpass.getpass("Password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Repeat password: "):
        print("Passwords must match and be at least 12 characters.")
        return 1
    try:
        create_user(argv[2], hash_password(password), argv[3])
    except DBError:
        print("Could not create the user. Does the username already exist?")
        return 1
    print(f"Created {argv[2].lower()} ({argv[3]}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))