from DrissionPage import ChromiumPage, ChromiumOptions
import time

from core.accounts import load_accounts, ACCOUNTS_FILE_PATH
from core.runner import run

TARGET_URL = (
    "https://login.eldorado.gg/login"
    "?redirect_uri=https%3A%2F%2Fwww.eldorado.gg%2Faccount%2Fauth-callback"
    "&response_type=code"
    "&client_id=3a4hal6jgl8gf5hnnjo06k05s5"
    "&identity_provider=COGNITO"
    "&scope=email%20openid%20profile%20aws.cognito.signin.user.admin"
    "&state=OmYu4EUM6uJfFHaouTdVK8yNzlqkeEB4"
    "&code_challenge=bPRJjuLrVzmCeXhxqzIZlT8k879rHnHI6KEE4TaLGjE"
    "&code_challenge_method=S256"
    "&lang=en"
)


def main():
    raw_accounts = load_accounts(ACCOUNTS_FILE_PATH)
    if not raw_accounts:
        print(f"Please add accounts to '{ACCOUNTS_FILE_PATH}' in USER:PASS format and restart.")
        return

    co = ChromiumOptions()
    co.headless(False)
    page = ChromiumPage(addr_or_opts=co)

    try:
        print("Navigating to Eldorado login page...")
        page.get(TARGET_URL)
        time.sleep(1.5)

        print(f"Loaded {len(raw_accounts)} accounts. Starting scan...\n")
        run(page, raw_accounts, TARGET_URL)

    finally:
        print("\nDone. Press Enter to close...")
        input()
        page.quit()


if __name__ == "__main__":
    main()
