#!/usr/bin/env python3
"""Announce a verified skieomod release in the configured Discord thread."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
GUILD_ID = '1476002317626114111'
THREAD_ID = '1557305192871886898'
WEBHOOK_ENV = 'SKIEOMOD_DISCORD_WEBHOOK_URL'
STATE_ENV = 'SKIEOMOD_DISCORD_STATE_DIR'
DOWNLOADS = 'https://skieomod.emillon.fr/downloads/'


class NotificationError(RuntimeError):
    def __init__(self, message, *, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


def release_notes(path, version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Use a release version such as 1.20.10')
    text = Path(path).read_text(encoding='utf-8')
    headings = list(re.finditer(r'^##\s+(.+)$', text, re.MULTILINE))
    entries = []
    for index, heading in enumerate(headings):
        if re.fullmatch(r'\[' + re.escape(version) + r'\](?:\s+-\s+\d{4}-\d{2}-\d{2})?', heading[1].strip()):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            entries.append(text[heading.end():end].strip())
    if len(entries) != 1 or not entries[0]:
        raise ValueError(f'Add exactly one nonempty ## [{version}] entry to the changelog')
    return entries[0]


def payload(path, version):
    notes = release_notes(path, version)
    heading = f'**skieomod / Custom Map {version}**\n\n'
    links = (f'\n\n[Release notes]({DOWNLOADS}Changelog-{version}.md) · '
             f'[Tools]({DOWNLOADS}CustomMap-Tools.zip) · '
             f'[Game loader]({DOWNLOADS}CustomMap-Mod.zip)')
    # A UTF-16 bound also fits Discord clients that count surrogate pairs.
    units = lambda text: len(text.encode('utf-16-le')) // 2
    budget = 2000 - units(heading + links)
    if units(notes) > budget:
        notes = notes.encode('utf-16-le')[:(budget - 2) * 2].decode('utf-16-le', errors='ignore').rstrip() + '…'
    return {'content': heading + notes + links, 'allowed_mentions': {'parse': []}}


def webhook_endpoint(value):
    parsed = urlsplit(value)
    match = re.fullmatch(r'/api/(?:v10/)?webhooks/([0-9]{17,20})/([A-Za-z0-9._-]+)', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'discord.com' or parsed.query or parsed.fragment or not match:
        raise ValueError('Configure a Discord incoming webhook URL in ' + WEBHOOK_ENV)
    return value, match[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def request_json(url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    request = Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'skieomod-release'})
    for attempt in range(3):
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                raw = response.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise NotificationError('Discord response exceeded its limit', ambiguous=body is not None)
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise NotificationError('Discord did not return a message confirmation', ambiguous=body is not None) from None
            if not isinstance(result, dict):
                raise NotificationError('Invalid Discord response', ambiguous=body is not None)
            return result
        except HTTPError as error:
            if error.code == 429 and attempt < 2:
                try:
                    delay = float(json.loads(error.read(8192)).get('retry_after', 0))
                except (ValueError, TypeError, AttributeError):
                    delay = 0
                if math.isfinite(delay) and 0 < delay <= 30:
                    time.sleep(delay)
                    continue
            raise NotificationError('Discord returned HTTP ' + str(error.code),
                                    ambiguous=body is not None and error.code >= 500) from None
        except (URLError, TimeoutError, OSError):
            raise NotificationError('Discord request did not complete; check the thread before retrying',
                                    ambiguous=body is not None) from None


def state_path(version, directory=None):
    folder = Path(directory or os.environ.get(STATE_ENV) or ROOT / 'build/discord-notifications')
    return folder / (THREAD_ID + '-' + version + '.json')


def verify_published_version(version):
    request = Request(DOWNLOADS + 'loader-latest.json', headers={'Cache-Control': 'no-cache', 'User-Agent': 'skieomod-release'})
    with urlopen(request, timeout=20) as response:
        data = response.read(1024 * 1024 + 1)
    feed = json.loads(data)
    if len(data) > 1024 * 1024 or not isinstance(feed, dict) or feed.get('release') != version:
        raise ValueError('Announce only the current verified published version')


def save_receipt(path, receipt):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def message_receipt(message, receipt):
    if not re.fullmatch(r'[0-9]{17,20}', str(message.get('id', ''))) or message.get('channel_id') != THREAD_ID:
        raise NotificationError('Discord did not confirm the requested thread/message', ambiguous=True)
    content = message.get('content')
    if not isinstance(content, str) or hashlib.sha256(content.encode('utf-8')).hexdigest() != receipt['content_sha256']:
        raise NotificationError('Discord message does not match the prepared announcement', ambiguous=True)
    return {**receipt, 'status': 'sent', 'message_id': message['id']}


def announce(version, changelog, *, webhook=None, directory=None, confirm_message_id=None):
    body = payload(changelog, version)
    endpoint, webhook_id = webhook_endpoint(webhook or os.environ.get(WEBHOOK_ENV, ''))
    path = state_path(version, directory)
    if path.is_file():
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(receipt, dict) or receipt.get('version') != version or receipt.get('thread_id') != THREAD_ID:
            raise NotificationError('Announcement receipt does not match this release/thread')
        digest = receipt.get('content_sha256')
        if receipt.get('status') not in ('pending', 'sent') or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise NotificationError('Announcement receipt is incomplete; inspect it before retrying')
        if receipt.get('status') == 'sent':
            if not re.fullmatch(r'[0-9]{17,20}', str(receipt.get('message_id', ''))):
                raise NotificationError('Confirmed receipt has no valid message ID')
            return receipt
        if not confirm_message_id:
            raise NotificationError('An announcement is pending. Check the thread and confirm its message ID; '
                                    'remove the pending receipt only after checking that no message was sent.')
        if not re.fullmatch(r'[0-9]{17,20}', confirm_message_id) or receipt.get('webhook_id') != webhook_id:
            raise ValueError('Use the original webhook and a valid message ID')
        message = request_json(endpoint + '/messages/' + confirm_message_id + '?' + urlencode({'thread_id': THREAD_ID}))
        receipt = message_receipt(message, receipt)
        save_receipt(path, receipt)
        return receipt
    if confirm_message_id:
        raise ValueError('No pending announcement exists for this release')
    metadata = request_json(endpoint)
    if metadata.get('guild_id') != GUILD_ID or metadata.get('id') != webhook_id or metadata.get('type') != 1:
        raise ValueError('Use an incoming webhook belonging to the requested Discord server')
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {'status': 'pending', 'version': version, 'thread_id': THREAD_ID,
               'webhook_id': webhook_id, 'content_sha256': hashlib.sha256(body['content'].encode('utf-8')).hexdigest()}
    # Claim the version before POST; concurrent runs cannot both announce it.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream)
    try:
        message = request_json(endpoint + '?' + urlencode({'wait': 'true', 'thread_id': THREAD_ID}), body)
        receipt = message_receipt(message, receipt)
        save_receipt(path, receipt)
    except NotificationError as error:
        if not error.ambiguous:
            path.unlink()
        raise
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('--changelog', type=Path, default=ROOT / 'CHANGELOG.md')
    parser.add_argument('--state-dir', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='print the message without accessing Discord')
    mode.add_argument('--confirm-message-id', help='recover a pending receipt using an existing webhook message; never sends')
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            print(json.dumps(payload(args.changelog, args.version), ensure_ascii=False, indent=2))
        else:
            if not args.confirm_message_id:
                verify_published_version(args.version)
            receipt = announce(args.version, args.changelog, directory=args.state_dir,
                               confirm_message_id=args.confirm_message_id)
            print(f'Discord announcement confirmed: {receipt["message_id"]}')
    except (OSError, ValueError, NotificationError) as error:
        print('Discord announcement failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
