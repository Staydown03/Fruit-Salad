"""Offline checks for manual TBA linking and saved OAuth credentials."""
import contextlib
from functools import partial
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_reliability import functions, module


class ManualLinkTests(unittest.TestCase):
    def setUp(self):
        with patch.dict('sys.modules', {'requests': Mock()}):
            self.links = module('TOOLS/manual_links.py', 'test_manual_links')

    def test_video_urls_and_ids_accept_common_formats(self):
        video_id = 'AbC_def-123'
        for value in (video_id, f'https://youtu.be/{video_id}?t=3', f'https://www.youtube.com/watch?v={video_id}&list=foo',
                      f'https://youtube.com/shorts/{video_id}', f'https://www.youtube.com/live/{video_id}'):
            self.assertEqual(self.links.youtube_id(value), video_id)
        for value in ('https://youtube.com/playlist?list=foo', 'https://evil.example/watch?v=AbC_def-123', 'bad'):
            with self.assertRaises(ValueError):
                self.links.youtube_id(value)

    def test_match_aliases_and_full_clip_names(self):
        for value, expected in [('Q1', 'qm1'), ('P9', 'sf9m1'), ('F2', 'f1m2'),
                                ('NJNOR_P9_1633.mp4', 'sf9m1'), ('sf4m2', 'sf4m2')]:
            self.assertEqual(self.links.match_key(value), expected)
        for value in ('P0', 'Q-1', 'not-a-match', 'sf1m0'):
            with self.assertRaises(ValueError):
                self.links.match_key(value)

    def test_replay_attempt_requires_explicit_local_filename(self):
        with patch.object(self.links, 'local_matches', return_value=['TEST_Q1_0900', 'TEST_Q1_1000']):
            with self.assertRaisesRegex(ValueError, 'Multiple local attempts'):
                self.links.prepare_link('Q1', 'AbC_def-123', 'TEST')
            item = self.links.prepare_link('TEST_Q1_1000.mp4', 'AbC_def-123', 'TEST')
        self.assertEqual(item['local_names'], ['TEST_Q1_1000'])
        with self.assertRaisesRegex(ValueError, 'different FIRST event'):
            self.links.prepare_link('OTHER_Q1_0900', 'AbC_def-123', 'TEST')

    def test_tba_failure_does_not_mark_clip_completed(self):
        item = {'match_key': 'qm1', 'video_id': 'AbC_def-123', 'local_names': ['TEST_Q1_0900']}
        with patch.object(self.links, 'postTheBlueAlliance', return_value=SimpleNamespace(status_code=403)), \
             patch.object(self.links.status, 'mark_manual_upload') as record:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                self.links.link_video('id', 'secret', '2026test', item)
        record.assert_not_called()

    def test_tba_success_records_manual_upload_and_supports_link_only(self):
        item = {'match_key': 'sf9m1', 'video_id': 'AbC_def-123', 'local_names': ['TEST_P9_1633']}
        with patch.object(self.links, 'postTheBlueAlliance', return_value=SimpleNamespace(status_code=200, json=lambda: {'Success': 'Match videos successfully updated'})) as post, \
             patch.object(self.links.status, 'mark_manual_upload') as record:
            self.links.link_video('id', 'secret', '2026test', item)
            record.assert_called_once_with('TEST_P9_1633', 'AbC_def-123', '2026test')
            post.assert_called_once_with('id', 'secret', '2026test', {'sf9m1': 'AbC_def-123'})
            record.reset_mock()
            self.links.link_video('id', 'secret', '2026test', item, remember=False)
            record.assert_not_called()

    def test_manual_record_preserves_old_logs_and_is_idempotent(self):
        status = module('TOOLS/status.py', 'manual_status')
        with tempfile.TemporaryDirectory() as folder:
            status.VIDEOS_FILE = str(Path(folder, 'videos.json'))
            Path(status.VIDEOS_FILE).write_text('{}')
            send = Path(folder, 'send.txt')
            send.write_text('TEST_Q2_1000\n')
            status.mark_manual_upload('TEST_Q1_0900', 'AbC_def-123', '2026test')
            status.mark_manual_upload('TEST_Q1_0900', 'AbC_def-123', '2026test')
            saved = status.video_record('TEST_Q1_0900')
            self.assertTrue(saved['manual'] and saved['tba'] and saved['metadata_done'])
            self.assertEqual(send.read_text().splitlines(), ['TEST_Q2_1000', 'TEST_Q1_0900'])
            backups = list(Path(folder, 'manual-link-backups').iterdir())
            self.assertEqual(len(backups), 4)
            self.assertTrue(all(p.stat().st_size > 0 for p in backups))


class TBAConfirmationTests(unittest.TestCase):
    def test_signature_matches_exact_post_body_and_redirects_are_disabled(self):
        requests = Mock()
        helper = functions('TOOLS/TBA.py', ['postTheBlueAlliance'], requests=requests, hashlib=hashlib, json=json)
        helper.postTheBlueAlliance('synthetic-id', 'synthetic-secret', '2026test', {'qm1': 'AbC_def-123'})
        call = requests.post.call_args
        body = call.kwargs['data']
        endpoint = '/api/trusted/v1/event/2026test/match_videos/add'
        expected = hashlib.md5(b'synthetic-secret' + endpoint.encode() + body).hexdigest()
        self.assertEqual(call.kwargs['headers']['X-TBA-Auth-Sig'], expected)
        self.assertEqual(json.loads(body), {'qm1': 'AbC_def-123'})
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertEqual(call.kwargs['headers']['Content-Type'], 'application/json')

    def test_http_200_without_explicit_tba_confirmation_is_rejected(self):
        helper = functions('TOOLS/TBA.py', ['require_tba_success'])
        for value in (None, [], {}, {'Error': 'failure'}, {'Success': ''}):
            with self.assertRaises(RuntimeError):
                helper.require_tba_success(SimpleNamespace(status_code=200, json=lambda: value))
        response = Mock(status_code=200)
        response.json.side_effect = ValueError('not JSON')
        with self.assertRaisesRegex(RuntimeError, 'no JSON confirmation'):
            helper.require_tba_success(response)
        helper.require_tba_success(SimpleNamespace(status_code=200, json=lambda: {'Success': 'Match videos successfully updated'}))

    def test_false_success_does_not_change_local_completion_records(self):
        with patch.dict('sys.modules', {'requests': Mock()}):
            links = module('TOOLS/manual_links.py', 'false_success_links')
        prepared = {'match_key': 'qm1', 'video_id': 'AbC_def-123', 'local_names': ['TEST_Q1_0900']}
        response = SimpleNamespace(status_code=200, json=lambda: {'Error': 'not accepted'})
        with patch.object(links, 'postTheBlueAlliance', return_value=response), \
             patch.object(links.status, 'mark_manual_upload') as record:
            with self.assertRaises(RuntimeError):
                links.link_video('synthetic-id', 'synthetic-secret', '2026test', prepared)
        record.assert_not_called()


class RefreshError(Exception):
    retryable = False


class TransportError(Exception):
    pass




if __name__ == '__main__':
    unittest.main()
