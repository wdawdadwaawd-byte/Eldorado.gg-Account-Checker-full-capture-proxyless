# How It Works

This project is an automated account checker for **Eldorado.gg**. It reads a list of `email:password` credentials, logs into each account through Eldorado's OAuth2/Cognito authentication system, collects account details (wallet balance, loyalty tier, suspension status, etc.), and sorts results into two output files.

---

## High-Level Architecture

The codebase is split into two layers that work together:

| Layer | Files | Responsibility |
|---|---|---|
| **Python** | `main.py`, `core/` | Browser lifecycle, loop orchestration, API calls, file I/O |
| **JavaScript** | `js/` | In-browser auth (PKCE generation, Cognito fingerprinting, login flow) |

The bridge between them is **DrissionPage** — a Python library that drives a Chromium browser via the Chrome DevTools Protocol (CDP). Python injects JavaScript into the browser tab and then reads results back through `window.*` globals.

---

## Entry Point — `main.py`

1. Loads `accounts.txt` (one `email:password` per line).
2. Opens a Chromium browser window with DrissionPage.
3. Navigates to the Eldorado OAuth2 authorization URL.
4. Calls `run()` from `core/runner.py` to process each account.
5. Closes the browser when done.

The URL in `main.py` contains a static `code_challenge` placeholder. This is only used to load the login page — the real, per-account PKCE pair is generated fresh inside the browser by JavaScript.

---

## Execution Flow

```
accounts.txt
     │
     ▼
main.py
  loads accounts, opens browser, navigates to login page
     │
     ▼
runner.py → run()
  for each account:
     │
     ├─ 1. Build JS bundle (logger + pkce + cognito + login)
     │       inject current account's email/password
     │
     ├─ 2. Run JS in browser tab
     │       login.js:
     │         a) generate PKCE pair (verifier + challenge)
     │         b) POST /login     → establishes Cognito session
     │         c) POST /verifyPassword → server returns auth code
     │         d) store auth_code + verifier in window globals
     │
     ├─ 3. Python detects success signal (window._wait_for_cookie_read)
     │
     ├─ 4. Navigate to auth-callback URL on www.eldorado.gg
     │
     ├─ 5. POST /api/authentication/authenticate
     │       exchange auth code + PKCE verifier for session cookies
     │
     ├─ 6. Call REST APIs to collect account info:
     │       GET /api/userpayment/me         → wallet balance
     │       GET /api/offerUser/me           → listing mode
     │       GET /api/loyalty/me             → loyalty tier + points
     │       GET /api/orders/me/pendingOrdersSum → pending orders
     │       GET /api/users/me               → username, 2FA, suspension
     │
     ├─ 7. Write to results_clean.txt or results_suspended.txt
     │
     └─ 8. Logout → move to next account
```

---

## Components

### `core/accounts.py` — Account I/O

Handles reading and writing account data.

- **`load_accounts(path)`** — reads `accounts.txt`, skips `#` comment lines.
- **`save_clean_account(line)`** — appends to `results_clean.txt`.
- **`save_suspended_account(line)`** — appends to `results_suspended.txt`.
- **`accounts_to_json(accounts)`** — serializes the account list to JSON for injection into JavaScript.

If `accounts.txt` doesn't exist, a sample file is created automatically.

---

### `core/browser.py` — Browser Bridge & API Helpers

This is the largest module with two roles:

**1. JS Bundle Assembly — `build_login_script()`**

Reads all four JS files from `js/`, replaces two placeholders in `login.js`:
- `__ACCOUNTS_JSON__` → the serialized account list
- `__CURRENT_INDEX__` → the current account's index

Then concatenates them in dependency order:
```
logger.js → pkce.js → cognito.js → login.js
```

The result is a single JS string that gets injected into the browser.

**2. Authenticated API Fetch Helpers**

Each helper:
1. Reads the `XSRF-TOKEN` cookie via CDP (to bypass `HttpOnly` restrictions).
2. Injects an async `fetch()` call that stores its result in a `window._xxx_result` global.
3. Polls that global for up to 10 seconds.
4. Parses and returns the JSON.

The `credentials: 'include'` option on every fetch ensures the browser's session cookies are automatically attached.

| Function | HTTP Call | Data Returned |
|---|---|---|
| `do_authenticate` | `POST /api/authentication/authenticate` | Sets session cookies |
| `do_user_payment` | `GET /api/userpayment/me` | Wallet balance |
| `do_offer_user_me` | `GET /api/offerUser/me` | Listing mode, verified seller |
| `do_loyalty_me` | `GET /api/loyalty/me` | Loyalty tier, points |
| `do_pending_orders_sum` | `GET /api/orders/me/pendingOrdersSum` | Pending order value |
| `do_users_me` | `GET /api/users/me` | Username, 2FA, suspension info |
| `do_logout` | `GET /logout?...` | Clears session |

---

### `core/runner.py` — Main Loop

`run(page, raw_accounts, target_url)` drives the per-account iteration.

Key behaviors:
- **Global reset** before each account — clears all `window._*` flags so state doesn't leak.
- **Poll loop** — checks `window._log_queue` (for JS console output) and `window._wait_for_cookie_read` (success signal) every 0.1s, with a 15-second timeout.
- **Cache flush** — calls `page.clear_cache()` every 200 accounts to prevent memory growth.

---

## JavaScript Components

### `js/logger.js` — Console Bridge

Wraps `console.log` and `console.error` to push messages onto `window._log_queue`. Python drains this queue each tick, so JavaScript's console output appears in the Python terminal. An IIFE guard prevents double-wrapping on re-injection.

---

### `js/pkce.js` — PKCE Key Generation

Implements **RFC 7636 PKCE** (Proof Key for Code Exchange) using the browser's Web Crypto API:

1. Generate 96 random bytes with `crypto.getRandomValues()`.
2. Base64url-encode them → the **verifier** (kept secret, sent later to exchange the code).
3. SHA-256 hash the verifier with `crypto.subtle.digest()`.
4. Base64url-encode the hash → the **challenge** (sent to the auth server upfront).

The verifier is stored in `window._code_verifier` for Python to retrieve after login.

---

### `js/cognito.js` — AWS Cognito ASF Fingerprinting

AWS Cognito's Advanced Security Features require a signed device fingerprint with every auth request. This module generates it:

| Function | Purpose |
|---|---|
| `_getDeviceId()` | Persistent random ID stored in `localStorage` |
| `_getContextData(username)` | Assembles payload: UA, device ID, language, platform, timezone |
| `_createSignature(payload, clientId)` | HMAC-SHA256 signs the payload using `clientId` as the key |
| `generateCognitoAsfData(clientId, username)` | Returns `btoa(JSON.stringify({ payload, signature, version }))` |

The final token is a base64-encoded JSON blob sent as `cognitoAsfData` in both login steps.

---

### `js/login.js` — Authentication Flow

The main JS entry point. Runs as an async IIFE:

1. **Select account** — deserializes `__ACCOUNTS_JSON__`, picks entry at `__CURRENT_INDEX__`.
2. **Read CSRF token** — reads `XSRF-TOKEN` from `document.cookie` (decoded from base64) or falls back to a DOM `<input>` element.
3. **Generate PKCE pair** — calls `generatePKCE()`, stores verifier in `window._code_verifier`.
4. **Step 1: POST `/login`** — sends `username + csrf + cognitoAsfData`. Establishes session on `login.eldorado.gg`.
5. **Step 2: POST `/verifyPassword`** — sends `password + csrf + new cognitoAsfData`. If successful, the server responds with a redirect header containing `?code=AUTH_CODE`.
6. **Signal Python** — stores `code` in `window._auth_code`, sets `window._wait_for_cookie_read = true`.
7. **On failure** — calls logout, sets `window._need_refresh = true` to skip to the next account.

> **Remix trick:** The login endpoints run on Remix.run. Appending `_data=routes/login` to the query string causes Remix to return JSON instead of an HTML page, making the flow scriptable without following HTML redirects.

---

## Python ↔ JavaScript Communication

Since Python and JavaScript run in different execution environments, they communicate through `window.*` globals that Python can both set and read via `page.run_js()`:

| Global | Set by | Read by | Meaning |
|---|---|---|---|
| `window._log_queue` | `logger.js` | `runner.py` | JS console output buffer |
| `window._wait_for_cookie_read` | `login.js` | `runner.py` | Login succeeded |
| `window._auth_code` | `login.js` | `runner.py` | OAuth2 authorization code |
| `window._code_verifier` | `login.js` | `runner.py` | PKCE verifier string |
| `window._need_refresh` | `login.js` | `runner.py` | Skip to next account |
| `window._last_success` | `login.js` | `runner.py` | Email:password of last success |
| `window._auth_result` | `browser.py` helpers | `browser.py` | API fetch result |

Python uses CDP (`Network.getAllCookies`) to read `HttpOnly` cookies that JavaScript cannot access directly — this is how the `XSRF-TOKEN` is obtained for API calls.

---

## Authentication Flow in Detail

```
Browser tab (login.eldorado.gg)          Server (Cognito / Eldorado)
─────────────────────────────────────    ───────────────────────────
1. Generate PKCE verifier + challenge
2. POST /login
   { username, csrf, cognitoAsfData,  ──► Cognito validates ASF token,
     code_challenge (S256) }               sets session cookie
3. POST /verifyPassword
   { password, csrf, cognitoAsfData } ──► Cognito verifies password,
                                          returns ?code=AUTH_CODE
4. window._auth_code = AUTH_CODE
   window._wait_for_cookie_read = true

Python (runner.py detects signal)
5. Navigate to https://www.eldorado.gg/account/auth-callback?code=AUTH_CODE
6. POST /api/authentication/authenticate
   { code, codeVerifier, redirectUrl } ──► Server verifies PKCE,
                                           sets __Host-EldoradoIdToken
                                           + __Host-EldoradoRefreshToken
7. API calls with session cookies ────────► Account data returned
```

---

## External Dependencies

| Dependency | Where | Purpose |
|---|---|---|
| `DrissionPage` | Python | Chromium automation via CDP |
| `Web Crypto API` | Browser built-in | SHA-256, HMAC-SHA256, random bytes |
| `localStorage` | Browser built-in | Persistent Cognito device ID |

The only Python package required is `DrissionPage`. There is no `requirements.txt` in the repo — install it with:

```bash
pip install DrissionPage
```

---

## Output Files

| File | Contents |
|---|---|
| `results_clean.txt` | Accounts that logged in successfully and are not suspended |
| `results_suspended.txt` | Accounts that are banned/suspended |

Each line in the output files contains the email, password, and collected account info (wallet, tier, points, etc.) formatted as a single string.
