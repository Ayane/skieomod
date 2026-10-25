"""HTTPS transport using Windows' native certificate chain validation."""
from __future__ import annotations

from functools import lru_cache
from datetime import datetime, timezone
import platform
import ssl
import sys
from urllib.request import HTTPSHandler
from urllib.request import build_opener as _build_opener, urlopen as _urlopen


@lru_cache(maxsize=1)
def windows_context():
    # CryptoAPI can refresh roots and fetch missing intermediates. Merely
    # copying Windows' certificate store into OpenSSL misses that chain repair.
    # Keep this context local to our requests; do not patch ssl globally.
    import truststore
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def urlopen(request, *, timeout):
    if sys.platform == 'win32':
        return _urlopen(request, timeout=timeout, context=windows_context())
    return _urlopen(request, timeout=timeout)


def build_opener(*handlers):
    if sys.platform == 'win32':
        handlers = (*handlers, HTTPSHandler(context=windows_context()))
    return _build_opener(*handlers)


def certificate_error(error):
    reason = getattr(error, 'reason', error)
    if not isinstance(reason, ssl.SSLCertVerificationError):
        return None
    detail = getattr(reason, 'verify_message', None) or str(reason)
    return ('HTTPS certificate verification failed: ' + detail + '. '
            'System UTC: ' + datetime.now(timezone.utc).isoformat(timespec='seconds') +
            '; Python ' + platform.python_version() + ' on ' + platform.platform() + '. '
            'Check your computer date and time, install operating system updates, '
            'then retry with the latest skieomod tools. '
            'If it still fails, report this message and your Windows/Python versions.')
