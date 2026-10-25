"""Publish validated map/mod archives to the web catalogue."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request

if __package__ == 'tools':
    from .skieo_http import build_opener
    from .custom_packages import ManifestError, inspect_package
    from .skieo_install import PRIMARY_REPOSITORY
else:
    from skieo_http import build_opener
    from custom_packages import ManifestError, inspect_package
    from skieo_install import PRIMARY_REPOSITORY


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a publishing token or retry a POST across a redirect.
        return None


def publish(archive, repository=None):
    origin = (repository or os.environ.get('CUSTOM_MAP_REPOSITORY') or PRIMARY_REPOSITORY).rstrip('/')
    # Migrate old CLI configurations before sending credentials (no HTTP redirect).
    if origin == 'https://skieomap.emillon.fr':
        origin = PRIMARY_REPOSITORY
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ManifestError('The publishing repository must be an HTTPS origin without credentials or a path')
    token = os.environ.get('CUSTOM_MAP_TOKEN', '').strip()
    if not token or len(token) > 512 or any(not 33 <= ord(char) <= 126 for char in token):
        raise ManifestError('Set CUSTOM_MAP_TOKEN to a publishing token from ' + origin + '/account')
    kind, manifest, _ = inspect_package(Path(archive))
    request = Request(origin + '/api/v1/packages?kind=' + kind, data=Path(archive).read_bytes(),
                      headers={'Content-Type': 'application/zip', 'Authorization': 'Bearer ' + token}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=180) as response:
            source = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        # A server response must not echo a token into terminal logs.
        raise ManifestError('Web publication failed (HTTP ' + str(error.code) +
                            '); check your token and whether this version is already published') from None
    if len(source) > 1024 * 1024:
        raise ManifestError('Web publication response exceeds 1 MiB; check the catalogue before retrying')
    result = json.loads(source)
    if (not isinstance(result, dict) or result.get('id') != manifest['id']
            or result.get('version') != manifest['metadata']['version']):
        raise ManifestError('Unexpected publication response; check the catalogue before retrying')
    return result
