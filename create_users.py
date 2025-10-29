import hashlib
import binascii
import os
import pandas as pd

USERS_FILE = "users.csv"
ITERATIONS = 200_000 

def create_user(username, password):
    # Generate random 16-byte salt (hex encoded)
    salt = binascii.hexlify(os.urandom(16)).decode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        binascii.unhexlify(salt),
        ITERATIONS
    )
    hash_hex = binascii.hexlify(dk).decode("utf-8")

    # Prepare new row
    new_row = {
        "username": username,
        "salt": salt,
        "hash": hash_hex,
        "iterations": str(ITERATIONS)
    }

    # Append or create new CSV
    if os.path.exists(USERS_FILE):
        df = pd.read_csv(USERS_FILE, dtype=str)
        if username in df.get("username", pd.Series(dtype=str)).tolist():
            raise ValueError(f"User '{username}' already exists.")
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    else:
        df = pd.DataFrame([new_row])

    df.to_csv(USERS_FILE, index=False)
    print(f"✅ User '{username}' created successfully.")

if __name__ == "__main__":
    username = input("Enter new username: ").strip()
    password = input("Enter password: ").strip()
    create_user(username, password)
