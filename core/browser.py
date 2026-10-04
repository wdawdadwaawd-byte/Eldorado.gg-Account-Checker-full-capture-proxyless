import os
import json
import time

# JS dosyalarının bulunduğu klasör
JS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "js")


def _read_js(filename):
    with open(os.path.join(JS_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


def build_login_script(accounts_json: str, current_index: int) -> str:
    """
    JS dosyalarını birleştirip tek bir çalıştırılabilir script üretir.
    login.js içindeki __ACCOUNTS_JSON__ ve __CURRENT_INDEX__ placeholder'larını inject eder.
    """
    logger_js  = _read_js("logger.js")
    pkce_js    = _read_js("pkce.js")
    cognito_js = _read_js("cognito.js")
    login_js   = _read_js("login.js")

    # Placeholder'ları değiştir
    login_js = login_js.replace("__ACCOUNTS_JSON__", accounts_json)
    login_js = login_js.replace("__CURRENT_INDEX__", str(current_index))

    return "\n".join([logger_js, pkce_js, cognito_js, login_js])


def get_all_cookies_via_cdp(page, domain: str) -> list:
    """Retrieve all cookies for a domain via CDP (including HttpOnly)."""
    try:
        result = page.run_cdp("Network.getAllCookies")
        all_cookies = result.get("cookies", [])
        return [c for c in all_cookies if domain in c.get("domain", "")]
    except Exception as e:
        print(f"[CDP ERROR] {e}")
        return []


def print_cookies(cookies: list, label: str):
    if not cookies:
        return
    print(f"[CDP] {label}:")
    for c in cookies:
        flags = (" [HttpOnly]" if c.get("httpOnly") else "") + (" [Secure]" if c.get("secure") else "")
        val_preview = c['value'][:80] + ("..." if len(c['value']) > 80 else "")
        print(f"  {c['name']}={val_preview}{flags} [Path={c.get('path', '/')}]")


def get_xsrf_token(page, domain="eldorado.gg") -> str:
    """Retrieve XSRF token for www.eldorado.gg via CDP."""
    try:
        result = page.run_cdp("Network.getAllCookies")
        for c in result.get("cookies", []):
            if "XSRF-TOKEN" in c["name"] and domain in c.get("domain", ""):
                return c["value"]
    except Exception as e:
        print(f"[XSRF ERROR] {e}")
    return ""


def do_authenticate(page, auth_code: str, code_verifier: str) -> dict:
    """
    www.eldorado.gg/api/authentication/authenticate isteğini JS fetch ile at.
    Auth-callback sayfasındayken çağrılmalı — www.eldorado.gg cookie'leri otomatik gider.
    """
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const xsrfToken = {json.dumps(xsrf_token)};
        const resp = await fetch('https://www.eldorado.gg/api/authentication/authenticate', {{
            method: 'POST',
            credentials: 'include',
            headers: {{
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': xsrfToken,
            }},
            body: JSON.stringify({{
                code: {json.dumps(auth_code)},
                codeVerifier: {json.dumps(code_verifier)},
                redirectUrl: 'https://www.eldorado.gg/account/auth-callback'
            }})
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._auth_result = JSON.stringify({{
            status: resp.status,
            body: body,
            usedXsrf: xsrfToken.substring(0, 20)
        }});
    }} catch(e) {{
        window._auth_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._auth_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._auth_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}


def do_logout(page):
    """Logout from login.eldorado.gg."""
    try:
        page.run_js("""
            fetch('https://login.eldorado.gg/logout?client_id=3a4hal6jgl8gf5hnnjo06k05s5&logout_uri=https%3A%2F%2Fwww.eldorado.gg%2F', {
                method: 'GET', credentials: 'include'
            }).catch(() => {});
        """)
    except:
        pass


def do_user_payment(page) -> dict:
    """GET /api/userpayment/me — wallet balance."""
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const resp = await fetch('https://www.eldorado.gg/api/userpayment/me', {{
            method: 'GET',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': {json.dumps(xsrf_token)},
                'X-Client-Build-Time': '2026-10-01_13:12:05',
            }}
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._payment_result = JSON.stringify({{ status: resp.status, body: body }});
    }} catch(e) {{
        window._payment_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._payment_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._payment_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}


def do_pending_orders_sum(page) -> dict:
    """
    GET /api/orders/me/pendingOrdersSum isteğini JS fetch ile at.
    """
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const xsrfToken = {json.dumps(xsrf_token)};
        const resp = await fetch('https://www.eldorado.gg/api/orders/me/pendingOrdersSum', {{
            method: 'GET',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': xsrfToken,
                'X-Client-Build-Time': '2026-10-01_13:12:05',
            }}
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._pending_orders_result = JSON.stringify({{ status: resp.status, body: body }});
    }} catch(e) {{
        window._pending_orders_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._pending_orders_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._pending_orders_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}


def do_users_me(page) -> dict:
    """
    GET /api/users/me isteğini JS fetch ile at.
    Response'da suspension alanı varsa hesap banlanmış demektir.
    """
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const xsrfToken = {json.dumps(xsrf_token)};
        const resp = await fetch('https://www.eldorado.gg/api/users/me', {{
            method: 'GET',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': xsrfToken,
                'X-Client-Build-Time': '2026-10-01_13:12:05',
                'Referer': 'https://www.eldorado.gg/suspended',
            }}
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._users_me_result = JSON.stringify({{ status: resp.status, body: body }});
    }} catch(e) {{
        window._users_me_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._users_me_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._users_me_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}


def do_loyalty_me(page) -> dict:
    """
    GET /api/loyalty/me isteğini JS fetch ile at.
    __Host-EldoradoIdToken cookie'si mevcut olmalı (authenticate sonrası).
    """
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const xsrfToken = {json.dumps(xsrf_token)};
        const resp = await fetch('https://www.eldorado.gg/api/loyalty/me', {{
            method: 'GET',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': xsrfToken,
                'X-Client-Build-Time': '2026-10-01_13:12:05',
            }}
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._loyalty_result = JSON.stringify({{ status: resp.status, body: body }});
    }} catch(e) {{
        window._loyalty_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._loyalty_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._loyalty_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}


def do_offer_user_me(page) -> dict:
    """
    GET /api/offerUser/me isteğini JS fetch ile at.
    __Host-EldoradoIdToken cookie'si mevcut olmalı (authenticate sonrası).
    """
    xsrf_token = get_xsrf_token(page)

    js = f"""
(async () => {{
    try {{
        const xsrfToken = {json.dumps(xsrf_token)};
        const resp = await fetch('https://www.eldorado.gg/api/offerUser/me', {{
            method: 'GET',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'X-Xsrf-Token': xsrfToken,
                'X-Client-Build-Time': '2026-10-01_13:12:05',
            }}
        }});
        const body = await resp.json().catch(() => ({{}}));
        window._offer_user_result = JSON.stringify({{ status: resp.status, body: body }});
    }} catch(e) {{
        window._offer_user_result = JSON.stringify({{ status: 0, error: e.toString() }});
    }}
}})();
"""
    page.run_js("window._offer_user_result = null;")
    page.run_js(js)

    for _ in range(100):
        time.sleep(0.1)
        try:
            result = page.run_js("return window._offer_user_result || null;")
            if result:
                return json.loads(result)
        except:
            pass
    return {"status": 0, "error": "timeout"}
