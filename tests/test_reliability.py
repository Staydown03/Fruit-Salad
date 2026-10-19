"""Offline regression tests. Never load credentials or modify event logs.

Run: python -m unittest discover -s tests -v
"""
import ast
import contextlib
import datetime
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, **namespace):
    """Exercise worker functions without importing GUI dependencies or secret files."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert len(selected) == len(names), names
    exec(compile(ast.Module(body=selected, type_ignores=[]), path, 'exec'), namespace)
    return SimpleNamespace(**namespace)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result






class NetworkTests(unittest.TestCase):
    def test_first_requests_are_bounded_and_http_errors_are_raised(self):
        request = Mock()
        helper = functions('TOOLS/FMS.py', ['_get_json'], requests=request, API_TIMEOUT=(10, 30))
        response = request.get.return_value
        response.json.return_value = {'Matches': []}
        self.assertEqual(helper._get_json('example', {}), {'Matches': []})
        self.assertEqual(request.get.call_args.kwargs['timeout'], (10, 30))
        response.raise_for_status.side_effect = RuntimeError('HTTP failure')
        with self.assertRaises(RuntimeError):
            helper._get_json('example', {})

    def test_failed_poll_retries_and_routes_saved_upload_directly_to_sender(self):
        stop = threading.Event()
        status = Mock()
        status.video_record.return_value = {'video_id': 'saved-id'}
        match = {'post': datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)}
        get = Mock(side_effect=[TimeoutError('simulated timeout'), []])
        def wait(_):
            if get.call_count >= 2:
                stop.set()
            return stop.is_set()
        stop.wait = Mock(side_effect=wait)
        build, send = queue.Queue(), queue.Queue()
        worker = functions('TOOLS/process_queue.py', ['process_queue_seek'],
            status=status, time=time, datetime=datetime, pytz=SimpleNamespace(timezone=lambda _: datetime.timezone.utc),
            getMatchesFromFMS=get, rewrapMatches=lambda *args: [match],
            listNotInLog=lambda *args: [match], match2str=lambda *args: 'TEST_Q1',
            queue_build=build, queue_send=send, incrementCountText=Mock(), open=Mock())
        worker.open.return_value.__enter__ = Mock(return_value=Mock())
        worker.open.return_value.__exit__ = Mock(return_value=False)
        cfg = {'program': 'FRC', 'season': {'year': 2026}, 'event': {'code': 'TEST', 'timezone': 'UTC'}}
        with contextlib.redirect_stdout(io.StringIO()):
            worker.process_queue_seek(cfg, stop, None, {'FRC_username': '', 'FRC_key': ''})
        self.assertEqual(get.call_count, 2)
        self.assertTrue(build.empty())
        self.assertEqual(send.get_nowait()['videoID'], 'saved-id')
        self.assertTrue(any(c.kwargs.get('ok') is False for c in status.update.call_args_list))
        self.assertTrue(any(c.kwargs.get('ok') is True for c in status.update.call_args_list))


class UploadTests(unittest.TestCase):
    def test_authentication_preserves_google_upload_transport_with_timeout(self):
        transport = SimpleNamespace(timeout=60, redirect_codes={301, 302, 307})
        api = Mock()
        api.http.build_http.return_value = transport
        auth = Mock()
        flow = Mock()
        worker = functions('TOOLS/YouTube.py', ['authenticate_youtube'],
            googleapiclient=api, google_auth_httplib2=auth,
            google_auth_oauthlib=SimpleNamespace(flow=flow),
            cached_credentials=Mock(return_value=None), save_credentials=Mock())
        worker.authenticate_youtube()
        api.http.build_http.assert_called_once_with()
        self.assertEqual(transport.timeout, 30)
        self.assertNotIn(308, transport.redirect_codes)
        self.assertIn(302, transport.redirect_codes)
        self.assertIs(auth.AuthorizedHttp.call_args.kwargs['http'], transport)
        self.assertIs(api.discovery.build.call_args.kwargs['http'], auth.AuthorizedHttp.return_value)

    def test_upload_id_is_checkpointed_before_metadata_failure(self):
        youtube = Mock()
        youtube.videos.return_value.insert.return_value.next_chunk.return_value = (None, {'id': 'saved-id'})
        checkpoint = Mock()
        def fail(*args):
            checkpoint.assert_called_once_with('saved-id')
            raise RuntimeError('metadata failed')
        worker = functions('TOOLS/YouTube.py', ['upload_video'],
            googleapiclient=SimpleNamespace(http=SimpleNamespace(MediaFileUpload=Mock())), finish_video=fail)
        with self.assertRaises(RuntimeError):
            worker.upload_video(youtube, 'clip.mp4', {}, on_uploaded=checkpoint)

    def test_playlist_retry_does_not_add_an_existing_video_twice(self):
        youtube = Mock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {'items': [{'id': 'present'}]}
        worker = functions('TOOLS/YouTube.py', ['finish_video'])
        worker.finish_video(youtube, 'saved-id', playlistID='playlist')
        youtube.playlistItems.return_value.insert.assert_not_called()

    def test_upload_checkpoint_survives_reload_and_corrupt_ledger_is_not_overwritten(self):
        status = module('TOOLS/status.py', 'test_status')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'videos.json'
            status.VIDEOS_FILE = str(path)
            status.record_video('TEST_Q1', video_id='saved-id')
            restarted = module('TOOLS/status.py', 'test_restarted_status')
            restarted.VIDEOS_FILE = str(path)
            self.assertEqual(restarted.video_record('TEST_Q1')['video_id'], 'saved-id')
            path.write_text('corrupt')
            with self.assertRaises(ValueError):
                restarted.video_record('TEST_Q1')
            with self.assertRaises(ValueError):
                restarted.record_video('TEST_Q2', video_id='other')
            self.assertEqual(path.read_text(), 'corrupt')

    def test_restart_finishes_saved_upload_without_uploading_again(self):
        status = Mock()
        status.video_record.return_value = {'video_id': 'saved-id', 'metadata_done': True}
        stop = threading.Event()
        send = queue.Queue()
        send.put({'id': 'Q1'})
        def done(_):
            stop.set()
        worker = functions('TOOLS/process_queue.py', ['process_queue_send'],
            queue_send=send, queue=queue, time=time, status=status,
            match2str=lambda *args: 'TEST_Q1', generateThumbnail=Mock(return_value='thumb.png'),
            formatYouTubeTitle=Mock(return_value='Title'), upload_video=Mock(), finish_video=Mock(),
            translateMatchString=lambda _: 'qm1', postTheBlueAlliance=Mock(return_value=SimpleNamespace(status_code=200)),
            incrementCountText=done, review=Mock(), open=Mock())
        worker.open.return_value.__enter__ = Mock(return_value=Mock())
        worker.open.return_value.__exit__ = Mock(return_value=False)
        cfg = {'program': 'FRC', 'event': {'code': 'TEST', 'forceDetails': False, 'logoSponsor': None, 'details': '', 'name': 'Test'},
               'season': {'year': 2026}, 'YouTube': {'description': '', 'tags': '', 'playlist': ''},
               'TBA': {'eventKey': 'test', 'Auth_Id': '', 'Auth_Secret': ''}}
        with contextlib.redirect_stdout(io.StringIO()):
            worker.process_queue_send(cfg, stop, None, object())
        worker.upload_video.assert_not_called()
        worker.finish_video.assert_not_called()
        worker.postTheBlueAlliance.assert_called_once_with('', '', 'test', {'qm1': 'saved-id'})


class BuildRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'event': {'code': 'TEST'}, 'season': {
            'secondsBeforeStart': 4, 'secondsOfMatch': 150, 'secondsAfterEnd': 3,
            'secondsBeforePost': 2, 'secondsAfterPost': 5}}
        self.match = {'id': 'Q1'}

    def helper(self, exists=True, failure=None):
        validate = Mock(side_effect=failure)
        return functions('TOOLS/process_queue.py', ['reuse_built_clip'],
            os=SimpleNamespace(path=SimpleNamespace(join=os.path.join, isfile=Mock(return_value=exists))),
            status=Mock(), time=time, subprocess=subprocess, validate_clip=validate,
            queue_send=Mock(), incrementCountText=Mock(), match2str=lambda *args: 'TEST_Q1_0900')

    def test_valid_existing_clip_is_queued_for_upload(self):
        helper = self.helper()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(helper.reuse_built_clip(self.cfg, self.match, None))
        helper.validate_clip.assert_called_once_with(os.path.join('output', 'TEST_Q1_0900.mp4'), 150)
        helper.queue_send.put.assert_called_once_with(self.match)
        helper.incrementCountText.assert_called_once()

    def test_missing_clip_requires_a_build(self):
        helper = self.helper(exists=False)
        self.assertFalse(helper.reuse_built_clip(self.cfg, self.match, None))
        helper.validate_clip.assert_not_called()
        helper.queue_send.put.assert_not_called()

    def test_invalid_or_too_short_clip_is_not_sent(self):
        for error in (RuntimeError('truncated clip'), ValueError('invalid duration'),
                      subprocess.CalledProcessError(1, 'ffprobe')):
            helper = self.helper(failure=error)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(helper.reuse_built_clip(self.cfg, self.match, None))
            helper.queue_send.put.assert_not_called()

    def test_probe_timeout_does_not_claim_that_existing_clip_is_invalid(self):
        helper = self.helper(failure=subprocess.TimeoutExpired('ffprobe', 30))
        with self.assertRaises(subprocess.TimeoutExpired):
            helper.reuse_built_clip(self.cfg, self.match, None)
        helper.queue_send.put.assert_not_called()

    def test_live_local_restart_reuses_clip_before_reading_missing_source_or_syncing(self):
        helper = self.helper()
        stop = threading.Event()
        helper.queue_send.put.side_effect = lambda _: stop.set()
        build = queue.Queue()
        build.put(self.match)
        cfg = dict(self.cfg, video={'recordingStartTime': '2026-10-17T09:00:00+00:00',
                                   'filePath': 'recording-no-longer-present.mkv', 'adaptiveSyncDelay': True})
        worker = functions('TOOLS/process_queue.py', ['process_queue_build_live_local'],
            datetime=datetime, time=time, queue=queue, queue_build=build, status=Mock(),
            reuse_built_clip=helper.reuse_built_clip, extract_audio_from_video=Mock(),
            build_video_ffmpeg=Mock(), build_video_moviepy=Mock())
        with contextlib.redirect_stdout(io.StringIO()):
            worker.process_queue_build_live_local(cfg, stop, None, {})
        helper.queue_send.put.assert_called_once_with(self.match)
        worker.extract_audio_from_video.assert_not_called()
        worker.build_video_ffmpeg.assert_not_called()
        worker.build_video_moviepy.assert_not_called()


class ClipTests(unittest.TestCase):
    def test_truncated_missing_video_and_invalid_duration_are_rejected(self):
        runner = Mock()
        validate = functions('TOOLS/process_queue.py', ['validate_clip'], subprocess=SimpleNamespace(run=runner), json=json, math=math).validate_clip
        for info in ({'format': {'duration': '2'}, 'streams': [{'codec_type': 'video'}]},
                     {'format': {'duration': '100'}, 'streams': [{'codec_type': 'audio'}]},
                     {'format': {'duration': 'nan'}, 'streams': [{'codec_type': 'video'}]}):
            runner.return_value.stdout = json.dumps(info)
            with self.assertRaises(RuntimeError):
                validate('clip.mp4', 100)
        runner.return_value.stdout = json.dumps({'format': {'duration': '100'}, 'streams': [{'codec_type': 'video'}]})
        validate('clip.mp4', 100)
        self.assertEqual(runner.call_args.kwargs['timeout'], 30)


    def test_duration_accepts_exact_match_or_longer_without_padding_requirements(self):
        runner = Mock()
        validate = functions('TOOLS/process_queue.py', ['validate_clip'], subprocess=SimpleNamespace(run=runner), json=json, math=math).validate_clip
        for duration in (150, 151, 164, 300, 3600):
            runner.return_value.stdout = json.dumps({'format': {'duration': str(duration)}, 'streams': [{'codec_type': 'video'}]})
            validate('clip.mp4', 150)
        for duration in (149.999, 140):
            runner.return_value.stdout = json.dumps({'format': {'duration': str(duration)}, 'streams': [{'codec_type': 'video'}]})
            with self.assertRaisesRegex(RuntimeError, 'shorter than'):
                validate('clip.mp4', 150)

    def test_ffmpeg_build_validates_against_match_duration_only(self):
        runner, validator = Mock(), Mock()
        fake_os = SimpleNamespace(replace=Mock(), remove=Mock(), path=SimpleNamespace(exists=Mock(return_value=False)))
        worker = functions('TOOLS/process_queue.py', ['build_video_ffmpeg'],
                           subprocess=SimpleNamespace(run=runner), validate_clip=validator, os=fake_os)
        cfg = {'video': {'filePath': 'source.mkv'}, 'season': {
            'secondsBeforeStart': 4, 'secondsOfMatch': 150, 'secondsAfterEnd': 3,
            'secondsBeforePost': 2, 'secondsAfterPost': 5}}
        worker.build_video_ffmpeg(cfg, 100, 250, 'output/match.mp4')
        validator.assert_called_once_with('output/match.mp4.pending.mp4', 150)
        fake_os.replace.assert_called_once_with('output/match.mp4.pending.mp4', 'output/match.mp4')


if __name__ == '__main__':
    unittest.main()
