// logger.js — Redirects console.log/error to window._log_queue array
// Python polls this array and drains it each tick

(function setupLogger() {
    if (window._logger_initialized) return;
    window._logger_initialized = true;

    const originalLog = console.log;
    const originalError = console.error;

    if (!window._log_queue) window._log_queue = [];

    console.log = function (...args) {
        originalLog.apply(console, args);
        window._log_queue.push(JSON.stringify({ type: "log", text: args.join(" ") }));
    };

    console.error = function (...args) {
        originalError.apply(console, args);
        window._log_queue.push(JSON.stringify({ type: "error", text: args.join(" ") }));
    };
})();
