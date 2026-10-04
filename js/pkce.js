// pkce.js — PKCE (Proof Key for Code Exchange) generation
// Usage: const pkce = await generatePKCE();
//        pkce.verifier  -> codeVerifier  (used in authenticate request)
//        pkce.challenge -> code_challenge (added to login URL)

async function generatePKCE() {
    const array = new Uint8Array(96);
    crypto.getRandomValues(array);

    const verifier = btoa(String.fromCharCode(...array))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');

    const encoder = new TextEncoder();
    const data = encoder.encode(verifier);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = new Uint8Array(hashBuffer);

    const challenge = btoa(String.fromCharCode(...hashArray))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');

    return { verifier, challenge };
}
