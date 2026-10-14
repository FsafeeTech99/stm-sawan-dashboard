"""Generate a password hash without putting a password in shell arguments."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.auth import hash_password

if __name__ == "__main__":
    password = getpass("Password (at least 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters")
    print(hash_password(password))
