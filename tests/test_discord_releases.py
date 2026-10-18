"""Discord announcements use mocked HTTP; no messages are sent by these tests."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from deployment import discord_releases as discord


class DiscordReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.changelog = self.root / 'CHANGELOG.md'
        self.changelog.write_text('# Changes\n\n## [Unreleased]\n\n- Future.\n\n## [1.20.10] - 2026-10-13\n\n- A useful fix.\n\n## [1.20.9]\n\n- Earlier.\n')
        self.version = '1.20.10'
        self.webhook_id = '123456789012345678'
        self.webhook = 'https://discord.com/api/webhooks/' + self.webhook_id + '/test-secret'
        self.metadata = {'id': self.webhook_id, 'guild_id': discord.GUILD_ID, 'type': 1}
        self.message = {'id': '987654321012345678', 'channel_id': discord.THREAD_ID,
                        'content': discord.payload(self.changelog, self.version)['content']}
        self.state = self.root / 'state'

    def announce(self, **kwargs):
        return discord.announce(self.version, self.changelog, webhook=self.webhook, directory=self.state, **kwargs)

    def test_notes_require_one_nonempty_entry_for_the_exact_release(self):
        self.assertEqual(discord.release_notes(self.changelog, self.version), '- A useful fix.')
        for text in ('## [Unreleased]\n\n- Future.\n', '## [1.20.10]\n',
                     '## [1.20.10]\n- A.\n## [1.20.10]\n- B.\n'):
            self.changelog.write_text(text)
            with self.assertRaises(ValueError): discord.release_notes(self.changelog, self.version)

    def test_long_unicode_notes_fit_discord_and_disable_mentions(self):
        self.changelog.write_text('## [1.20.10]\n\n- @everyone ' + '🏔' * 2500)
        body = discord.payload(self.changelog, self.version)
        self.assertLessEqual(len(body['content'].encode('utf-16-le')) // 2, 2000)
        self.assertIn('Changelog-1.20.10.md', body['content'])
        self.assertEqual(body['allowed_mentions'], {'parse': []})

    def test_only_canonical_discord_webhooks_are_accepted_without_echoing_tokens(self):
        for url in ('http://discord.com/api/webhooks/123/test-secret',
                    self.webhook.replace('discord.com', 'example.com'), self.webhook + '?x=1',
                    self.webhook.replace('/api/webhooks/', '/channels/')):
            with self.assertRaises(ValueError) as failure: discord.webhook_endpoint(url)
            self.assertNotIn('test-secret', str(failure.exception))

    def test_preview_uses_no_webhook_and_never_contacts_the_network(self):
        with patch.object(discord, 'request_json') as request, patch.object(discord, 'urlopen') as public, \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(discord.main([self.version, '--changelog', str(self.changelog), '--dry-run']), 0)
        request.assert_not_called(); public.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), discord.payload(self.changelog, self.version))

    def test_success_targets_thread_waits_for_confirmation_and_deduplicates(self):
        with patch.object(discord, 'request_json', side_effect=[self.metadata, self.message]) as request:
            receipt = self.announce()
            repeated = self.announce()
        self.assertEqual(receipt, repeated)
        self.assertEqual(receipt['status'], 'sent')
        self.assertEqual(request.call_count, 2)
        endpoint, body = request.call_args.args
        self.assertIn('wait=true', endpoint)
        self.assertIn('thread_id=' + discord.THREAD_ID, endpoint)
        self.assertEqual(body['allowed_mentions'], {'parse': []})
        self.assertNotIn('test-secret', discord.state_path(self.version, self.state).read_text())

    def test_wrong_server_is_rejected_before_post_or_receipt_creation(self):
        with patch.object(discord, 'request_json', return_value={**self.metadata, 'guild_id': 'wrong'}) as request:
            with self.assertRaises(ValueError): self.announce()
        request.assert_called_once_with(self.webhook)
        self.assertFalse(self.state.exists())

    def test_definite_rejection_can_be_retried_but_uncertain_delivery_cannot(self):
        with patch.object(discord, 'request_json', side_effect=[self.metadata, discord.NotificationError('HTTP 403')]):
            with self.assertRaises(discord.NotificationError): self.announce()
        self.assertFalse(discord.state_path(self.version, self.state).exists())
        with patch.object(discord, 'request_json', side_effect=[self.metadata, discord.NotificationError('Timeout', ambiguous=True)]):
            with self.assertRaises(discord.NotificationError): self.announce()
        with patch.object(discord, 'request_json') as request:
            with self.assertRaisesRegex(discord.NotificationError, 'pending'): self.announce()
        request.assert_not_called()

    def test_pending_receipt_can_be_recovered_using_a_read_only_message_lookup(self):
        with patch.object(discord, 'request_json', side_effect=[self.metadata, discord.NotificationError('Timeout', ambiguous=True)]):
            with self.assertRaises(discord.NotificationError): self.announce()
        with patch.object(discord, 'request_json', return_value=self.message) as request:
            receipt = self.announce(confirm_message_id=self.message['id'])
        request.assert_called_once_with(self.webhook + '/messages/' + self.message['id'] + '?thread_id=' + discord.THREAD_ID)
        self.assertEqual(receipt['status'], 'sent')

    def test_wrong_confirmation_keeps_the_pending_receipt(self):
        with patch.object(discord, 'request_json', side_effect=[self.metadata, {**self.message, 'channel_id': 'wrong'}]):
            with self.assertRaises(discord.NotificationError): self.announce()
        state = json.loads(discord.state_path(self.version, self.state).read_text())
        self.assertEqual(state['status'], 'pending')

    def test_corrupt_receipt_never_causes_a_second_send(self):
        path=discord.state_path(self.version,self.state);path.parent.mkdir()
        path.write_text(json.dumps({'version':self.version,'thread_id':discord.THREAD_ID,'status':'pending','content_sha256':None}))
        with patch.object(discord,'request_json') as request:
            with self.assertRaises(discord.NotificationError):self.announce()
        request.assert_not_called()

    def test_rate_limit_retries_the_requested_delay(self):
        limit = HTTPError(self.webhook, 429, 'limit', {}, io.BytesIO(b'{"retry_after":0.25}'))
        with patch.object(discord, 'build_opener') as opener, patch.object(discord.time, 'sleep') as sleep:
            opener.return_value.open.side_effect = [limit, io.BytesIO(json.dumps(self.message).encode())]
            self.assertEqual(discord.request_json(self.webhook, {'content': 'test'}), self.message)
        sleep.assert_called_once_with(.25)

    def test_transport_errors_are_redacted_and_mark_post_delivery_uncertain(self):
        with patch.object(discord, 'build_opener') as opener:
            opener.return_value.open.side_effect = URLError(self.webhook)
            with self.assertRaises(discord.NotificationError) as failure:
                discord.request_json(self.webhook, {'content': 'test'})
        self.assertTrue(failure.exception.ambiguous)
        self.assertNotIn('test-secret', str(failure.exception))

    def test_unpublished_version_is_rejected_by_standalone_guard(self):
        with patch.object(discord, 'urlopen', return_value=io.BytesIO(b'{"release":"1.20.9"}')):
            with self.assertRaises(ValueError): discord.verify_published_version(self.version)


if __name__ == '__main__': unittest.main()
