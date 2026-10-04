// cognito.js — AWS Cognito ASF (Advanced Security Features) data generation
// Computes device fingerprint, timezone, device ID and signs with HMAC-SHA256

const COGNITO_VERSION = "TS20240811";
const COGNITO_STORAGE_KEY = "Amazon.AWS.Cognito.ContextData.LS_UBID";

function _randomId() {
    return Math.random().toString(36).substring(2, 10);
}

function _generateDeviceId() {
    return `${_randomId()}${_randomId()}:${Date.now()}`;
}

function _getDeviceId() {
    let id = localStorage.getItem(COGNITO_STORAGE_KEY);
    if (!id) {
        id = _generateDeviceId();
        localStorage.setItem(COGNITO_STORAGE_KEY, id);
    }
    return id;
}

function _getTimezone() {
    const offset = new Date().getTimezoneOffset();
    const sign = offset > 0 ? "-" : "";
    const abs = Math.abs(offset);
    return `${sign}${Math.floor(abs / 60).toString().padStart(2, "0")}:${(abs % 60).toString().padStart(2, "0")}`;
}

function _getFingerprint(ua, plugins, lang) {
    return `${ua}${Array.from(plugins || []).reduce((s, p) => s + p.name + ":", "")}${lang}`;
}

function _getContextData(usernameForCognito = "") {
    const nav = window.navigator;
    return {
        contextData: {
            UserAgent: nav.userAgent,
            DeviceId: _getDeviceId(),
            DeviceLanguage: nav.language,
            DeviceFingerprint: _getFingerprint(nav.userAgent, nav.plugins, nav.language),
            DeviceConnectionType: nav.connection?.type,
            DevicePlatform: nav.platform,
            ClientTimezone: _getTimezone()
        },
        username: usernameForCognito,
        userPoolId: "",
        timestamp: Date.now().toString()
    };
}

async function _createSignature(payload, clientId, version) {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
        "raw",
        encoder.encode(clientId),
        { name: "HMAC", hash: { name: "SHA-256" } },
        false,
        ["sign"]
    );
    const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(version + payload));
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

async function generateCognitoAsfData(clientId, usernameForCognito = "") {
    const payloadObj = _getContextData(usernameForCognito);
    const payload = JSON.stringify(payloadObj);
    const signature = await _createSignature(payload, clientId, COGNITO_VERSION);
    return btoa(JSON.stringify({ payload, signature, version: COGNITO_VERSION }));
}
