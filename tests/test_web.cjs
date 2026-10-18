// Backward-compatible entry point for the local website checks.
process.env.CUSTOM_MAP_WEB_URL ||= 'http://127.0.0.1:8091';
require('./test_web_csp.cjs');
