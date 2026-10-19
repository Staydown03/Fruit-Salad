import json         # status files
import os           # atomic replace
import threading    # FRUIT's queues run on threads
import time         # timestamps
import shutil
import uuid

"""

Live status shared between FRUIT's worker threads and the dashboard.

    log/status.json  what each worker (seek / build / send) is doing right now, plus recent errors
    log/videos.json  every match video FRUIT has uploaded: YouTube ID, title, TBA link state

"""

STATUS_FILE = 'log/status.json'
VIDEOS_FILE = 'log/videos.json'

_lock = threading.Lock()
_status = {'running': False, 'seek': {}, 'build': {}, 'send': {}, 'errors': []}


def _write(path, data):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as file:
            json.dump(data, file, indent=1, default=str)
        os.replace(tmp, path)
    except OSError:
        pass    # a reader had the file open; the next update will land


def update(worker:str, **fields):
    """Record what a worker is doing, e.g. update('send', match='ABCD_Q12_1224', phase='uploading', progress=0.4)"""
    with _lock:
        _status.setdefault(worker, {}).update(fields, updated=time.time())
        _write(STATUS_FILE, _status)


def set_running(running:bool):
    with _lock:
        _status['running'] = running
        _status['started'] = time.time() if running else _status.get('started')
        _write(STATUS_FILE, _status)


def error(worker:str, message):
    """Keep the last 20 errors for the dashboard"""
    with _lock:
        _status['errors'] = (_status['errors'] + [{'t': time.time(), 'worker': worker, 'message': str(message)[:300]}])[-20:]
        _write(STATUS_FILE, _status)


def record_video(match_str:str, **fields):
    """Remember an uploaded match video, e.g. record_video('ABCD_Q12_1224', video_id='abc', tba=True)"""
    with _lock:
        try:
            with open(VIDEOS_FILE) as file:
                videos = json.load(file)
        except FileNotFoundError:
            videos = {}
        videos.setdefault(match_str, {}).update(fields, updated=time.time())
        # This is the recovery record: a failed write must prevent the worker from
        # proceeding as though the upload were safely checkpointed.
        tmp = VIDEOS_FILE + '.tmp'
        with open(tmp, 'w') as file:
            json.dump(videos, file, indent=1, default=str)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, VIDEOS_FILE)


def video_record(match_str):
    """Load an upload checkpoint after a restart; never silently ignore a corrupt ledger."""
    with _lock:
        try:
            with open(VIDEOS_FILE) as file:
                return json.load(file).get(match_str, {})
        except FileNotFoundError:
            return {}


def mark_manual_upload(match_str, video_id, event_key):
    """Record a user-supplied upload after TBA accepts it; preserve old logs first."""
    with _lock:
        send_file = os.path.join(os.path.dirname(VIDEOS_FILE), 'send.txt')
        folder = os.path.join(os.path.dirname(VIDEOS_FILE), 'manual-link-backups')
        os.makedirs(folder, exist_ok=True)
        for path in (VIDEOS_FILE, send_file):
            if os.path.exists(path) and os.path.getsize(path):
                backup = os.path.join(folder, os.path.basename(path) + '.' + uuid.uuid4().hex)
                shutil.copy2(path, backup)
                if os.path.getsize(backup) != os.path.getsize(path) or not os.path.getsize(backup):
                    raise OSError('Could not verify local processing-log backup')
        try:
            with open(VIDEOS_FILE) as file:
                videos = json.load(file)
        except FileNotFoundError:
            videos = {}
        videos.setdefault(match_str, {}).update(video_id=video_id, tba=True,
            tba_event_key=event_key, metadata_done=True, manual=True, updated=time.time())
        pending = VIDEOS_FILE + '.tmp'
        with open(pending, 'w') as file:
            json.dump(videos, file, indent=1)
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, VIDEOS_FILE)
        # Append only after the video checkpoint is durable; retries are idempotent.
        try:
            with open(send_file) as file:
                sent = set(file.read().splitlines())
        except FileNotFoundError:
            sent = set()
        if match_str not in sent:
            with open(send_file, 'a') as file:
                file.write(match_str + '\n')
                file.flush()
                os.fsync(file.fileno())
