"""Validate and link manually uploaded YouTube videos without Google authorization."""
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
from TOOLS.TBA import postTheBlueAlliance, require_tba_success
from TOOLS import status

LOCAL_MATCH = re.compile(r'^([A-Za-z0-9]+)_([QPMF][1-9][0-9]*)_([0-9]{4})$', re.I)
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')


def youtube_id(value):
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value if '://' in value else 'https://' + value)
    host = (parsed.hostname or '').lower()
    pieces = parsed.path.strip('/').split('/')
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('Enter a YouTube URL or 11-character video ID.')
    if host in ('youtu.be', 'www.youtu.be') and len(pieces) == 1:
        result = pieces[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if parsed.path == '/watch':
            result = parse_qs(parsed.query).get('v', [''])[0]
        elif len(pieces) == 2 and pieces[0] in ('shorts', 'live', 'embed'):
            result = pieces[1]
        else:
            result = ''
    else:
        result = ''
    if not VIDEO_ID.fullmatch(result):
        raise ValueError('Enter a YouTube video URL or 11-character video ID, not a channel/playlist URL.')
    return result


def match_key(value):
    value = Path(value.strip()).stem
    local = LOCAL_MATCH.fullmatch(value)
    if local:
        value = local.group(2)
    if re.fullmatch(r'[Qq][1-9][0-9]*', value):
        return 'qm' + value[1:]
    if re.fullmatch(r'[PpMm][1-9][0-9]*', value):
        return 'sf' + value[1:] + 'm1'
    if re.fullmatch(r'[Ff][1-9][0-9]*', value):
        return 'f1m' + value[1:]
    value = value.lower()
    if re.fullmatch(r'(?:qm[1-9][0-9]*|(?:ef|qf|sf|f)[1-9][0-9]*m[1-9][0-9]*)', value):
        return value
    raise ValueError('Use Q1, P9, F1, a local clip filename, or an exact TBA match key such as qm1/sf9m1.')


def local_matches(first_code):
    names = {p.stem for p in Path('output').glob('*.mp4')}
    for filename in ('log/seek.txt', 'log/send.txt'):
        try:
            names.update(Path(filename).read_text().splitlines())
        except FileNotFoundError:
            pass
    return sorted(name for name in names if (m := LOCAL_MATCH.fullmatch(name))
                  and m.group(1).upper() == first_code.upper())


def prepare_link(match, video, first_code='', remember=True):
    key, video_id = match_key(match), youtube_id(video)
    original = Path(match.strip()).stem
    full = LOCAL_MATCH.fullmatch(original)
    if full and first_code and full.group(1).upper() != first_code.upper():
        raise ValueError('The clip filename belongs to a different FIRST event code.')
    candidates = []
    if remember and first_code:
        names = local_matches(first_code)
        candidates = [n for n in names if n.upper() == original.upper()] if full else [n for n in names if match_key(n) == key]
        if len(candidates) > 1:
            raise ValueError('Multiple local attempts match this number. Use the full clip filename to choose one.')
    return {'match_key': key, 'video_id': video_id, 'local_names': candidates}


def link_video(auth_id, auth_secret, event_key, prepared, remember=True):
    """Called only after the user checks mappings and presses the publish button."""
    if not re.fullmatch(r'[0-9]{4}[a-z0-9]+', event_key):
        raise ValueError('Enter a TBA event key such as 2026abcd in The Blue Alliance tab.')
    if not auth_id or not auth_secret:
        raise ValueError('Fill in the TBA Auth ID and Auth Secret in The Blue Alliance tab.')
    try:
        response = postTheBlueAlliance(auth_id, auth_secret, event_key,
                                      {prepared['match_key']: prepared['video_id']})
    except Exception:
        raise RuntimeError('TBA connection failed or timed out. Check TBA before retrying.') from None
    require_tba_success(response)
    if remember:
        for name in prepared['local_names']:
            try:
                status.mark_manual_upload(name, prepared['video_id'], event_key)
            except Exception:
                raise RuntimeError('TBA accepted the link, but the local completion record could not be saved. Retry to finish recording it.') from None
    count = len(prepared['local_names']) if remember else 0
    return 'Linked to TBA (API confirmed; public page may be cached)' + ('; local clip marked completed' if count else '; no local completion record changed')
