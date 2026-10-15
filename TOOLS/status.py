import json         # status files
import os           # atomic replace
import threading    # FRUIT's queues run on threads
import time         # timestamps

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
        except (OSError, ValueError):
            videos = {}
        videos.setdefault(match_str, {}).update(fields, updated=time.time())
        _write(VIDEOS_FILE, videos)
