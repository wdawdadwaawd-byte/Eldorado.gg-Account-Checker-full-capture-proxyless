# Codebase Investigation Report

## Summary

This project is an automated **Eldorado.gg account scanner/checker**. It takes a list of `email:password` credentials, logs into each account via the Eldorado.gg OAuth2/Cognito authentication system, retrieves account details (wallet balance, loyalty tier, suspension status, pending orders, offer settings), and sorts accounts into two output files: `results_clean.txt` for active accounts and `results_suspended.txt` for banned ones.

The architecture splits responsibilities across Python (orchestration, browser control, API calls) and JavaScript (in-browser auth logic, PKCE generation, Cognito fingerprinting), bridged through DrissionPage's `run_js()` / CDP interface.

---

## Architecture Overview

```
main.py
  └─ loads accounts.txt
  └─ opens Chromium via DrissionPage
  └─ calls core/runner.py → run()
        └─ for each account:
              ├─ builds JS bundle via core/browser.py → build_login_script()
              ├─ injects + runs it in the browser (js/logger.js + js/pkce.js + js/cognito.js + js/login.js)
              ├─ polls window globals for results
              ├─ if login succeeded:
              │     ├─ navigates to auth-callback URL
              │     ├─ core/browser.py → do_authenticate()       (POST /api/authentication/authenticate)
              │     ├─ core/browser.py → do_user_payment()       (GET  /api/userpayment/me)
              │     ├─ core/browser.py → do_offer_user_me()      (GET  /api/offerUser/me)
              │     ├─ core/browser.py → do_loyalty_me()         (GET  /api/loyalty/me)
              │     ├─ core/browser.py → do_pending_orders_sum() (GET  /api/orders/me/pendingOrdersSum)
              │     ├─ core/browser.py → do_users_me()           (GET  /api/users/me)
              │     └─ core/accounts.py → save_clean/suspended_account()
              └─ core/browser.py → do_logout()
```

---

## Component Breakdown

### `main.py` — Entry Point

- Defines `TARGET_URL`: the Eldorado OAuth2 authorization URL with a hardcoded `state`, `code_challenge`, and `code_challenge_method=S256`. Note: the challenge here is a static placeholder; the real dynamic PKCE is generated per-account in JavaScript.
- Creates a **non-headless** Chromium instance via `DrissionPage.ChromiumPage`.
- Navigates to the login page, then hands off to `run()`.
- Closes the browser on exit (after user presses Enter).

**Key dependency:** `DrissionPage` — a Python browser automation library built on top of Chrome DevTools Protocol (CDP).

---

### `core/accounts.py` — Account I/O

| Symbol | Purpose |
|---|---|
| `ACCOUNTS_FILE_PATH` | Path to input file (`accounts.txt`) |
| `CLEAN_ACCOUNTS_FILE` | Output for non-suspended accounts (`results_clean.txt`) |
| `SUSPENDED_ACCOUNTS_FILE` | Output for suspended accounts (`results_suspended.txt`) |
| `load_accounts(path)` | Reads `email:password` lines, strips comments (`#`), returns list |
| `save_clean_account(line)` | Appends formatted result line to `results_clean.txt` |
| `save_suspended_account(line)` | Appends formatted result line to `results_suspended.txt` |
| `accounts_to_json(accounts)` | Serializes the account list to a JSON string for JS injection |

Input format: one `email:password` per line; lines starting with `#` are ignored. If the file doesn't exist, a sample file is created automatically.

---

### `core/browser.py` — Browser Bridge & API Calls

This is the largest module. It has two responsibilities:

**1. JS Bundle Assembly (`build_login_script`)**

Reads all four JS files from the `js/` directory, replaces two placeholders in `login.js`:
- `__ACCOUNTS_JSON__` → serialized account list
- `__CURRENT_INDEX__` → current account index (integer)

Then concatenates them in dependency order:
```
logger.js + pkce.js + cognito.js + login.js
```

The result is a single script string injected into the browser page with `page.run_js()`.

**2. Authenticated API Fetch Helpers**

Each helper follows the same pattern:
1. Retrieve the `XSRF-TOKEN` cookie via CDP (`get_xsrf_token`).
2. Build an async JS `fetch()` call that stores its result in a `window._xxx_result` global.
3. Poll `window._xxx_result` in a Python loop (up to 10 seconds, 100 × 0.1s ticks).
4. Parse and return the JSON result.

| Function | Endpoint | Purpose |
|---|---|---|
| `do_authenticate` | `POST /api/authentication/authenticate` | Exchange auth code + PKCE verifier for session cookies |
| `do_user_payment` | `GET /api/userpayment/me` | Wallet balance (amount, currency, USD equivalent) |
| `do_offer_user_me` | `GET /api/offerUser/me` | Listing mode, verified gift card seller status |
| `do_loyalty_me` | `GET /api/loyalty/me` | Loyalty tier, points balance, total points |
| `do_pending_orders_sum` | `GET /api/orders/me/pendingOrdersSum` | Total value of pending orders |
| `do_users_me` | `GET /api/users/me` | Username, email, 2FA, verified seller, suspension info |
| `do_logout` | `GET /logout?...` | Clears login.eldorado.gg session |
| `get_all_cookies_via_cdp` | CDP `Network.getAllCookies` | Retrieves all cookies including HttpOnly |
| `get_xsrf_token` | CDP `Network.getAllCookies` | Extracts XSRF-TOKEN for `www.eldorado.gg` |

The `credentials: 'include'` flag on every fetch ensures browser cookies are automatically sent, which is essential since the session tokens are `HttpOnly` cookies invisible to JavaScript directly.

---

### `core/runner.py` — Main Scanning Loop

`run(page, raw_accounts, target_url)` is the core orchestration function.

**Per-account flow:**

1. **Initialize window globals**: Resets all `window._*` flags so each account starts clean.
2. **Inject JS bundle**: Calls `build_login_script()` and runs it via `page.run_js()`.
3. **Poll loop (15-second timeout)**:
   - Drains `window._log_queue` each tick (0.1s) — printing JS console output to Python's stdout.
   - Checks `window._wait_for_cookie_read` — the success signal set by `login.js` when an auth code is obtained.
4. **On success signal**:
   - Reads `window._auth_code` and `window._code_verifier`.
   - Navigates to `https://www.eldorado.gg/account/auth-callback?code=...` to establish the `www.eldorado.gg` session.
   - Calls `do_authenticate()` to exchange the code for session cookies.
   - Calls the six API helpers to gather account info.
   - Builds a formatted `save_line` string and writes it to the appropriate result file.
   - Calls `do_logout()`.
5. **Advance**: Increments `current_index`, navigates back to `target_url`, sleeps 1 second.
6. **Cache flush**: Every 200 accounts, calls `page.clear_cache()` to prevent memory growth.

---

## JavaScript Components

### `js/logger.js` — Log Bridge

Wraps `console.log` and `console.error` to push JSON-encoded messages onto `window._log_queue`. Python drains this array each tick, making JS console output visible in the Python terminal. The IIFE guard (`if (window._logger_initialized) return`) prevents double-wrapping across re-injections.

### `js/pkce.js` — PKCE Key Generation

Implements RFC 7636 PKCE (Proof Key for Code Exchange):

1. Generates 96 random bytes via `crypto.getRandomValues()`.
2. Base64url-encodes them → `verifier` (the secret).
3. SHA-256 hashes the verifier via `crypto.subtle.digest()`.
4. Base64url-encodes the hash → `challenge` (sent to the authorization server).

Returns `{ verifier, challenge }`. The verifier is stored in `window._code_verifier` and later sent to `do_authenticate()`.

### `js/cognito.js` — AWS Cognito ASF Fingerprinting

AWS Cognito's Advanced Security Features (ASF) require a device fingerprint token with every authentication request. This module generates it:

| Function | Purpose |
|---|---|
| `_getDeviceId()` | Persistent random device ID stored in `localStorage` |
| `_getTimezone()` | UTC offset formatted as `±HH:MM` |
| `_getFingerprint(ua, plugins, lang)` | Concatenates UA + plugin names + language |
| `_getContextData(username)` | Assembles the full context payload (UA, device ID, language, fingerprint, platform, timezone) |
| `_createSignature(payload, clientId, version)` | HMAC-SHA256 signs the payload using `clientId` as the key, returns base64 |
| `generateCognitoAsfData(clientId, username)` | Combines payload + signature + version into a base64-encoded JSON token |

The final token is `btoa(JSON.stringify({ payload, signature, version: "TS20240811" }))`.

This token is sent as `cognitoAsfData` in both the login and verifyPassword POST requests.

### `js/login.js` — Authentication Flow

The main JS entry point. Runs as an async IIFE. Flow:

1. **Parse accounts**: Deserializes `__ACCOUNTS_JSON__` and selects account at `__CURRENT_INDEX__`.
2. **Get CSRF token**: Reads the `XSRF-TOKEN` cookie from `document.cookie`, decodes it (it's a base64-encoded JWT-like structure), or falls back to a DOM `<input>` query.
3. **Generate PKCE pair**: Calls `generatePKCE()`, stores `verifier` in `window._code_verifier`.
4. **Step 1 — Login POST**: Sends `username + csrf + cognitoAsfData` to `/login?..._data=routes/login`. This establishes the Cognito session on `login.eldorado.gg`.
5. **Step 2 — VerifyPassword POST**: Sends `password + csrf + cognitoAsfData` to `/verifyPassword?..._data=routes/verifyPassword`.
6. **Handle response**:
   - If the response header `x-remix-redirect` contains `auth-callback?code=`, the login succeeded. Extracts `code`, stores in `window._auth_code`, sets `window._wait_for_cookie_read = true`.
   - If `responseData.formError` is present, logs `[FAILED]` with the reason.
   - Otherwise logs `[UNKNOWN]`.
7. **On failure**: Calls the logout endpoint and sets `window._need_refresh = true` to signal Python to advance.

The `_data=routes/...` query parameter is a Remix.run framework convention that causes the server to return JSON instead of HTML for `fetch()` requests.

---

## Data / Execution Flow

```
accounts.txt
    │  (email:password lines)
    ▼
main.py → load_accounts()
    │  (List[str])
    ▼
runner.py → run()
    │
    ├─► build_login_script(accounts_json, current_index)
    │       Reads logger.js + pkce.js + cognito.js + login.js
    │       Injects accounts + index into login.js
    │       Returns concatenated JS string
    │
    ├─► page.run_js(script)   [runs in browser tab]
    │       login.js:
    │         1. generateCognitoAsfData()  →  cognitoAsfData token
    │         2. POST /login               →  sets session cookies on login.eldorado.gg
    │         3. generateCognitoAsfData()  →  new token for password step
    │         4. POST /verifyPassword      →  server redirects with ?code=AUTH_CODE
    │         5. Sets window._auth_code, window._code_verifier, window._wait_for_cookie_read
    │
    ├─► (Python detects window._wait_for_cookie_read == true)
    │
    ├─► page.get(auth-callback URL)        →  lands on www.eldorado.gg, gets XSRF cookie
    │
    ├─► do_authenticate(auth_code, code_verifier)
    │       POST /api/authentication/authenticate
    │       Body: { code, codeVerifier, redirectUrl }
    │       Result: sets __Host-EldoradoIdToken + __Host-EldoradoRefreshToken cookies
    │
    ├─► do_user_payment()     →  wallet balance
    ├─► do_offer_user_me()    →  listing/offline mode
    ├─► do_loyalty_me()       →  loyalty tier + points
    ├─► do_pending_orders_sum() → pending order value
    ├─► do_users_me()         →  username, 2FA, suspension
    │
    ├─► save_clean_account() or save_suspended_account()
    │
    └─► do_logout() → next account
```

---

## Key Algorithms and Notable Logic

### PKCE (RFC 7636)

A fresh PKCE pair is generated **per account per run** inside the browser (`pkce.js`). The verifier is a 128-character base64url string from 96 random bytes. The challenge is its SHA-256 hash, also base64url-encoded. This is the correct implementation of S256 as specified in RFC 7636.

The static `code_challenge` in `TARGET_URL` (main.py) is a placeholder that gets the page loaded; the **real** challenge used for each auth session comes from `pkce.js` and is embedded in the `BASE_PARAMS` constructed inside `login.js`.

### Cognito ASF Token

Cognito's Advanced Security Features require a device fingerprint to detect anomalous sign-ins. The token encodes:
- Browser User-Agent, platform, language, plugins
- A persistent device ID (localStorage-backed, so it stays the same across calls for the same browser session)
- Client timezone
- An HMAC-SHA256 signature using the Cognito `client_id` as the HMAC key

### Window Global Signaling

Python and JavaScript communicate through `window.*` globals since `run_js()` can both set and read them:

| Global | Set by | Read by | Meaning |
|---|---|---|---|
| `window._log_queue` | `logger.js` | `runner.py` | Console output buffer |
| `window._wait_for_cookie_read` | `login.js` | `runner.py` | Login succeeded, ready for Python to proceed |
| `window._auth_code` | `login.js` | `runner.py` | OAuth2 authorization code |
| `window._code_verifier` | `login.js` | `runner.py` | PKCE verifier for token exchange |
| `window._need_refresh` | `login.js` / `runner.py` | `runner.py` | Signal to break inner poll loop |
| `window._script_finished` | `login.js` | *(unused in runner)* | Script completed |
| `window._last_success` | `login.js` | `runner.py` | `email:password` of last success |
| `window._auth_result` | `browser.py` fetch helpers | `browser.py` | Result of API fetch calls |

### Remix `_data` Trick

The login endpoints are served by a Remix.run application. Appending `_data=routes/login` to a POST request's query string causes Remix to return a JSON response (loader/action data) instead of a full HTML page redirect, making the auth flow scriptable without following redirects.

---

## Python–JavaScript Relationship

| Concern | Handled by |
|---|---|
| Browser lifecycle, navigation | Python (`main.py`, DrissionPage) |
| Account file I/O | Python (`core/accounts.py`) |
| Cookie/CDP access | Python (`core/browser.py`, `get_all_cookies_via_cdp`) |
| Post-auth API calls | Python (`core/browser.py` fetch helpers via `run_js`) |
| Result storage | Python (`core/accounts.py`) |
| PKCE generation | JavaScript (`js/pkce.js`) — uses Web Crypto API |
| Cognito ASF token | JavaScript (`js/cognito.js`) — uses Web Crypto + browser fingerprint |
| Login / verifyPassword flow | JavaScript (`js/login.js`) — runs inside the browser tab |
| Console bridging | JavaScript (`js/logger.js`) — `window._log_queue` |

JavaScript runs **inside the live browser tab** and has access to the browser's `document.cookie`, `localStorage`, `crypto`, and same-origin `fetch`. Python uses CDP to read cookies that are `HttpOnly` (not accessible to JS) and to drive navigation.

---

## External Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| `DrissionPage` | Python (pip) | Chromium browser automation via CDP |
| `crypto.subtle` (Web Crypto API) | Browser built-in | SHA-256 hashing and HMAC signing in JS |
| `crypto.getRandomValues` | Browser built-in | Secure random byte generation |
| `localStorage` | Browser built-in | Persistent device ID for Cognito ASF |

There is no `requirements.txt` in the repository. The only Python dependency is `DrissionPage`.

---

## Conclusions

1. **The project is a credential checker** (sometimes called a "checker" or "account scanner") for the Eldorado.gg marketplace. It systematically logs in with user-supplied credentials and collects account information.

2. **The authentication flow is technically sophisticated**: it correctly implements OAuth2 with PKCE (S256), replicates Cognito's ASF device-fingerprinting protocol, and handles the Remix.run JSON response convention — all running inside a real browser to pass bot-detection checks.

3. **Python drives the outer loop**; JavaScript handles the inner browser-side auth because it needs access to the browser context (cookies, `crypto`, same-origin fetch).

4. **Communication between Python and JS** is entirely through `window.*` globals polled by Python in tight loops — a simple but effective IPC mechanism given the constraints of browser automation.

5. **No retry logic** exists for network timeouts beyond the `AbortController` (8s). A single `[SYSTEM ERROR]` in the outer runner skips the account without retry.

6. **Cache is only cleared every 200 accounts**, which may cause memory pressure on large account lists.

7. **The static `state` and `code_challenge` in `TARGET_URL`** are not security-relevant here since they are only used to get the login page to load. Each actual auth session uses a fresh PKCE pair and a hardcoded but consistent `state` value (`XbANFvjOIGeUrUsY7d4WXUpJ5f8E1CPV`) defined in `login.js`.
