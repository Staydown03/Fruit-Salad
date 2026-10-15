import json         # review file
import os           # atomic replace
import threading    # FRUIT's queues run on threads
import time         # timestamps

"""

Optional confirmation of each clip before FRUIT uploads it.

    log/review.json  {"enabled": bool, "matches": {match_str: {"state": "pending"|"approved"|"rejected",
                                                               "clip": path, "title": str}}}

The switch can be flipped at any time (FRUIT's checkbox or the dashboard); the send queue checks it for every
match, so it takes effect immediately.

"""

REVIEW_FILE = 'log/review.json'
_lock = threading.Lock()


def _load():
    try:
        with open(REVIEW_FILE) as file:
            data = json.load(file)
    except (OSError, ValueError):
        data = {}
    data.setdefault('enabled', False)
    data.setdefault('matches', {})
    return data


def _save(data):
    tmp = REVIEW_FILE + '.tmp'
    with open(tmp, 'w') as file:
        json.dump(data, file, indent=1)
    for _ in range(5):
        try:
            os.replace(tmp, REVIEW_FILE)
            return
        except PermissionError:     # another process is reading it; try again shortly
            time.sleep(0.1)


def enabled():
    return _load()['enabled']


def set_enabled(on:bool):
    with _lock:
        data = _load()
        data['enabled'] = bool(on)
        _save(data)


def state(match_str:str):
    """'pending', 'approved', 'rejected', or None if the match hasn't been submitted for review"""
    return _load()['matches'].get(match_str, {}).get('state')


def submit(match_str:str, clip:str, title:str):
    with _lock:
        data = _load()
        data['matches'][match_str] = {'state': 'pending', 'clip': clip, 'title': title, 'submitted': time.time()}
        _save(data)


def decide(match_str:str, decision:str):
    """decision: 'approved' or 'rejected'"""
    with _lock:
        data = _load()
        if match_str in data['matches'] and decision in ('approved', 'rejected', 'pending'):
            data['matches'][match_str].update(state=decision, decided=time.time())
            _save(data)


def pending():
    return {k: v for k, v in _load()['matches'].items() if v.get('state') == 'pending'}


def all_matches():
    return _load()['matches']
