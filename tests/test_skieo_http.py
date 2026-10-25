import contextlib
import io
from pathlib import Path
import re
import ssl
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request

from tools import custom_map as cli, skieo_http as http


class HttpsTests(unittest.TestCase):
    def tearDown(self):
        http.windows_context.cache_clear()

    def test_documented_package_index_resolves_the_runtime_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / 'pyproject.toml').read_text()
        declarations = re.search(r'(?m)^dependencies = \[(.*)\]$', project)[1]
        names = re.findall(r'"([A-Za-z0-9_.-]+)[^"\n]*"', declarations)
        self.assertIn('truststore', names)
        nginx = (root / 'deployment/nginx.conf').read_text()
        route = re.search(r'location ~ (\^/downloads/pypi/\([^\n]+)\s+\{', nginx)[1].strip()
        for name in names:
            self.assertRegex('/downloads/pypi/' + name.lower().replace('_', '-') + '/', route)

    def test_windows_uses_a_verified_native_context_without_global_injection(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        native = SimpleNamespace(SSLContext=Mock(return_value=context))
        request = Request('https://example.com/file')
        with patch.dict(sys.modules, truststore=native), patch.object(http.sys, 'platform', 'win32'), \
                patch.object(http, '_urlopen', return_value='response') as transport:
            self.assertEqual(http.urlopen(request, timeout=30), 'response')
            http.urlopen(request, timeout=5)
        native.SSLContext.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(transport.call_args.kwargs, {'timeout': 5, 'context': context})

    def test_publishing_keeps_its_redirect_handler_and_uses_the_same_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        redirect = HTTPRedirectHandler()
        with patch.object(http.sys, 'platform', 'win32'), \
                patch.object(http, 'windows_context', return_value=context), \
                patch.object(http, '_build_opener') as build:
            http.build_opener(redirect)
        handlers = build.call_args.args
        self.assertIs(handlers[0], redirect)
        self.assertIsInstance(handlers[1], HTTPSHandler)
        self.assertIs(handlers[1]._context, context)

    def test_other_platforms_keep_the_default_transport(self):
        with patch.object(http.sys, 'platform', 'linux'), \
                patch.object(http, 'windows_context', side_effect=AssertionError('Windows backend used')), \
                patch.object(http, '_urlopen') as transport, patch.object(http, '_build_opener') as build:
            http.urlopen('https://example.com', timeout=30)
            http.build_opener()
        transport.assert_called_once_with('https://example.com', timeout=30)
        build.assert_called_once_with()

    def test_certificate_failures_propagate_without_an_unverified_retry(self):
        error = URLError(ssl.SSLCertVerificationError(1, 'certificate has expired'))
        with patch.object(http.sys, 'platform', 'win32'), \
                patch.object(http, 'windows_context', return_value=object()), \
                patch.object(http, '_urlopen', side_effect=error) as transport:
            with self.assertRaises(URLError) as caught:
                http.urlopen('https://example.com', timeout=30)
        self.assertIs(caught.exception, error)
        transport.assert_called_once()

    def test_setup_explains_certificate_failures_and_preserves_other_errors(self):
        error = URLError(ssl.SSLCertVerificationError(1, 'certificate has expired'))
        output = io.StringIO()
        with patch.object(cli.desktop, 'setup', side_effect=error), contextlib.redirect_stderr(output):
            self.assertEqual(cli.main(['setup']), 2)
        self.assertIn('HTTPS certificate verification failed', output.getvalue())
        self.assertIn('date and time', output.getvalue())
        self.assertIn('Windows/Python versions', output.getvalue())
        self.assertIsNone(http.certificate_error(URLError('network unavailable')))


if __name__ == '__main__':
    unittest.main()
