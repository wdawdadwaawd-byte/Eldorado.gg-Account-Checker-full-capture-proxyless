import os
import json

ACCOUNTS_FILE_PATH = "accounts.txt"
CLEAN_ACCOUNTS_FILE   = "results_clean.txt"
SUSPENDED_ACCOUNTS_FILE = "results_suspended.txt"


def load_accounts(file_path=ACCOUNTS_FILE_PATH):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("example@gmail.com:password123\n")
        print(f"[INFO] '{file_path}' not found, a sample file was created. Please add your accounts.")
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    valid = []
    for line in lines:
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            valid.append(line)
    return valid


def save_clean_account(line: str):
    """Save a non-suspended account to results_clean.txt"""
    with open(CLEAN_ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_suspended_account(line: str):
    """Save a suspended account to results_suspended.txt"""
    with open(SUSPENDED_ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def accounts_to_json(accounts):
    return json.dumps(accounts)
