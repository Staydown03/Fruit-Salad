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


class PreviewTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(sys.modules, {'requests': Mock(), 'pytz': Mock()}):
            self.d = module('dashboard.py', 'test_dashboard')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d.THUMB = str(Path(self.temp.name) / 'live.jpg')
        self.old = b'\xff\xd8old frame\xff\xd9'
        Path(self.d.THUMB).write_bytes(self.old)

    def test_failed_or_incomplete_extract_preserves_previous_image(self):
        for result in (SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)):
            def fake(cmd, **kw):
                Path(cmd[-1]).write_bytes(b'partial')
                return result
            with patch.object(self.d, 'run', side_effect=fake):
                with self.assertRaises(RuntimeError):
                    self.d.extract_preview('recording.mkv', 120)
            self.assertEqual(Path(self.d.THUMB).read_bytes(), self.old)
            self.assertFalse(Path(self.d.THUMB + '.pending.jpg').exists())

    def test_timeout_preserves_previous_image(self):
        with patch.object(self.d, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 20)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.d.extract_preview('recording.mkv', 120)
        self.assertEqual(Path(self.d.THUMB).read_bytes(), self.old)

    def test_success_publishes_only_complete_replacement(self):
        new = b'\xff\xd8new frame\xff\xd9'
        def fake(cmd, **kw):
            self.assertEqual(Path(self.d.THUMB).read_bytes(), self.old)
            self.assertEqual(kw['timeout'], 20)
            Path(cmd[-1]).write_bytes(new)
            return SimpleNamespace(returncode=0)
        with patch.object(self.d, 'run', side_effect=fake):
            self.d.extract_preview('recording.mkv', 120)
        self.assertEqual(Path(self.d.THUMB).read_bytes(), new)

    def test_media_timeout_keeps_frame_age_and_checks_audio_independently(self):
        recording = Path(self.temp.name) / 'source.mkv'
        recording.write_bytes(b'fake recording')
        self.d.media = {'path': str(recording), 'thumb_at': 123, 'thumb_time': 'old'}
        with patch.object(self.d, 'read_json', return_value={'video': {'filePath': str(recording)}}), \
             patch.object(self.d, 'run', return_value=SimpleNamespace(stdout='100')), \
             patch.object(self.d, 'extract_preview', side_effect=subprocess.TimeoutExpired('ffmpeg', 20)), \
             patch.object(self.d, 'mean_volume', return_value=-20), \
             patch.object(self.d.glob, 'glob', return_value=[]):
            self.d.collect_media()
        self.assertEqual(self.d.media['thumb_at'], 123)
        self.assertIn('timed out', self.d.media['preview_error'])
        self.assertEqual(self.d.media['audio_db'], -20)

    def test_silent_and_failed_audio_are_distinct(self):
        with patch.object(self.d, 'run', return_value=SimpleNamespace(returncode=0, stderr='mean_volume: -inf dB')):
            self.assertEqual(self.d.mean_volume([]), -100)
        with patch.object(self.d, 'run', return_value=SimpleNamespace(returncode=1, stderr='')):
            self.assertIsNone(self.d.mean_volume([]))

    def test_event_collection_never_runs_ffmpeg_and_includes_upcoming_schedule(self):
        self.d.ROOT = self.temp.name
        Path(self.temp.name, 'output').mkdir()
        cfg = {'event': {'code': 'TEST', 'timezone': 'UTC'}, 'season': {'year': 2026}}
        review = SimpleNamespace(enabled=lambda: False, all_matches=lambda: {})
        upcoming = {'tournamentLevel': 'Qualification', 'matchNumber': 2, 'startTime': None, 'teams': []}
        def read(path, default=None):
            return cfg if path == 'CONFIG' else default
        with patch.object(self.d, 'read_json', side_effect=read), \
             patch.object(self.d, 'read_lines', return_value=[]), \
             patch.object(self.d, 'first_api', return_value=([], [upcoming])), \
             patch.object(self.d, 'run', return_value=SimpleNamespace(stdout='1')) as run, \
             patch.dict(sys.modules, {'TOOLS.review': review}), \
             patch('TOOLS.review', review, create=True), \
             patch.object(self.d.os, 'chdir'):
            self.d.collect()
        self.assertTrue(self.d.state['api_ok'])
        self.assertEqual(self.d.state['next_up']['number'], 2)
        self.assertTrue(all(c.args[0][0] not in ('ffmpeg', 'ffprobe') for c in run.call_args_list))


class ClipAudioCacheTests(unittest.TestCase):
    def setUp(self):
        PreviewTests.setUp(self)
        self.d.ROOT = self.temp.name
        self.d.AUDIO_CACHE = str(Path(self.temp.name) / '.cache' / 'clip-audio.json')
        Path(self.temp.name, 'output').mkdir()

    def clip(self, name, seconds_ago):
        path = Path(self.temp.name, 'output', name + '.mp4')
        path.write_bytes(b'fake clip')
        stamp = time.time() - seconds_ago
        os.utime(path, (stamp, stamp))
        return str(path)

    def test_measurements_survive_restart_but_changed_clips_are_invalidated(self):
        clip = self.clip('TEST_Q1', 100)
        with patch.object(self.d, 'mean_volume', return_value=-22) as probe:
            self.d.collect_clip_audio()
            self.d.collect_clip_audio()
        probe.assert_called_once()
        self.d.clip_audio.clear()
        self.d.load_clip_audio_cache()
        self.assertEqual(self.d.clip_audio[clip][2], -22)
        original = os.stat(clip)
        Path(clip).write_bytes(b'replaced clip with the same timestamp but a different size')
        os.utime(clip, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.d.clip_audio.clear()
        self.d.load_clip_audio_cache()
        self.assertNotIn(clip, self.d.clip_audio)
        with patch.object(self.d, 'mean_volume', return_value=-18):
            self.d.collect_clip_audio()
        self.assertEqual(self.d.clip_audio[clip][2], -18)

    def test_failure_does_not_starve_later_clips_and_is_retried(self):
        first = self.clip('TEST_Q2', 200)
        second = self.clip('TEST_Q10', 100)
        with patch.object(self.d, 'mean_volume', side_effect=[None, -20]) as probe:
            self.d.collect_clip_audio()
            self.d.collect_clip_audio()
        self.assertEqual(probe.call_args_list[0].args[0][-1], first)
        self.assertEqual(probe.call_args_list[1].args[0][-1], second)
        self.assertIn('will retry', self.d.clip_audio_checks[first]['status'])
        self.assertEqual(self.d.clip_audio[second][2], -20)
        with patch.object(self.d, 'mean_volume') as probe:
            self.d.collect_clip_audio()
        probe.assert_not_called()
        self.d.clip_audio_checks[first]['at'] -= 61
        with patch.object(self.d, 'mean_volume', return_value=-21):
            self.d.collect_clip_audio()
        self.assertEqual(self.d.clip_audio[first][2], -21)
        self.assertNotIn(first, self.d.clip_audio_checks)

    def test_corrupt_cache_is_ignored_and_incomplete_outputs_are_skipped(self):
        cache = Path(self.d.AUDIO_CACHE)
        cache.parent.mkdir()
        cache.write_text('broken cache')
        self.d.load_clip_audio_cache()
        self.clip('TEST_Q1.pending', 100)
        with patch.object(self.d, 'mean_volume') as probe:
            self.d.collect_clip_audio()
        probe.assert_not_called()


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
