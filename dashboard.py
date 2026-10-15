"""
FRUIT dashboard  ->  http://localhost:8765

Starts automatically with FRUIT (or run on its own: python dashboard.py). Shows what FRUIT is doing (from
log/status.json, written by the seek/build/send queues), the event's matches from the FIRST API, the health of the
recording, and the optional clip confirmation.
"""
import base64
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pytz
import requests

ROOT = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
PORT = 8765
CACHE = os.path.join(tempfile.gettempdir(), 'fruit_dashboard')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
os.makedirs(CACHE, exist_ok=True)

if not shutil.which('ffmpeg'):  # FRUIT's launcher normally puts ffmpeg on PATH; fall back to a winget install
    hits = glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin'))
    if hits:
        os.environ['PATH'] = hits[0] + os.pathsep + os.environ['PATH']

state = {'updated': None}
lock = threading.Lock()
clip_audio = {}     # clip path -> (mtime, dB)
prev_size = {}      # recording -> (time, bytes)


def path_in_root(*parts):
    return os.path.join(ROOT, *parts)


def read_json(path, default=None):
    try:
        with open(path_in_root(path)) as file:
            return json.load(file)
    except (OSError, ValueError):
        return default


def read_lines(path):
    try:
        with open(path_in_root(path)) as file:
            return [line.strip() for line in file if line.strip()]
    except OSError:
        return []


def run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout, creationflags=NO_WINDOW)


def mean_volume(args):
    out = run(['ffmpeg', '-hide_banner', '-nostdin', *args, '-vn', '-af', 'volumedetect', '-f', 'null', '-']).stderr
    m = re.search(r'mean_volume:\s*(-?[\d.]+) dB', out)
    return float(m.group(1)) if m else None


def hhmm(dt):
    return dt.strftime('%H:%M:%S') if dt else ''


# ---------------- FIRST API ----------------
def first_api(creds, year, code):
    auth = base64.b64encode(f"{creds['FRC_username']}:{creds['FRC_key']}".encode()).decode()
    headers = {'Authorization': 'Basic ' + auth}
    base = f'https://frc-api.firstinspires.org/v3.0/{year}'
    matches, schedule = [], []
    for level in ('Qualification', 'Playoff'):
        r = requests.get(f'{base}/matches/{code}', params={'tournamentLevel': level}, headers=headers, timeout=15)
        r.raise_for_status()
        matches += r.json()['Matches']
        r = requests.get(f'{base}/schedule/{code}', params={'tournamentLevel': level}, headers=headers, timeout=15)
        r.raise_for_status()
        schedule += r.json()['Schedule']
    return matches, schedule


def fruit_id(m, all_matches):
    """Same match IDs FRUIT uses (TOOLS/FMS.py rewrapMatches)"""
    if m['tournamentLevel'] == 'Playoff' and 'Final' in m.get('description', ''):
        n = len([x for x in all_matches if x['tournamentLevel'] == 'Playoff' and 'Final' not in x.get('description', '')])
        return 'F' + str(m['matchNumber'] - n)
    return m['tournamentLevel'][0] + str(m['matchNumber'])


def parse_time(s, tz):
    return tz.localize(datetime.datetime.strptime(s.split('.')[0], '%Y-%m-%dT%H:%M:%S')) if s else None


# ---------------- collector ----------------
def collect():
    errors = []
    now = datetime.datetime.now().astimezone()
    cfg = read_json('CONFIG')
    if not cfg:
        errors.append('No baked CONFIG yet - load your config in FRUIT and press Bake CONFIG.')
        cfg = {}
    event = cfg.get('event', {})
    code, year = event.get('code', ''), cfg.get('season', {}).get('year', datetime.date.today().year)
    tz = pytz.timezone(event.get('timezone') or 'America/New_York')
    season, video = cfg.get('season', {}), cfg.get('video', {})
    rec_path = video.get('filePath')
    rec_start = None
    if video.get('recordingStartTime'):
        try:
            rec_start = datetime.datetime.fromisoformat(video['recordingStartTime'])
        except ValueError:
            pass

    fruit = read_json('log/status.json', {}) or {}
    videos = read_json('log/videos.json', {}) or {}
    seen, sent = set(read_lines('log/seek.txt')), set(read_lines('log/send.txt'))
    outdir = path_in_root('output')
    outputs = {os.path.splitext(f)[0]: os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith('.mp4')} if os.path.isdir(outdir) else {}

    from TOOLS import review   # imported here so the dashboard works from any working directory
    os.chdir(ROOT)
    review_data = {'enabled': review.enabled(), 'matches': review.all_matches()}

    rows, api_ok = [], False
    try:
        creds = read_json('CREDENTIALS', {})
        raw, schedule = first_api(creds, year, code) if code else ([], [])
        api_ok = bool(code)
        sched_time = {(s['tournamentLevel'], s['matchNumber']): s.get('startTime') for s in schedule}
        for m in raw:
            mid = fruit_id(m, raw)
            start, post = parse_time(m.get('actualStartTime'), tz), parse_time(m.get('postResultTime'), tz)
            sched = parse_time(sched_time.get((m['tournamentLevel'], m['matchNumber'])), tz)
            name = f'{code}_{mid}_{start.hour:02}{start.minute:02}' if start else None
            clip = outputs.get(name) if name else None
            db = None
            if clip:
                mt = os.path.getmtime(clip)
                if clip in clip_audio and clip_audio[clip][0] == mt:
                    db = clip_audio[clip][1]
                elif time.time() - mt > 10:
                    db = mean_volume(['-i', clip])
                    clip_audio[clip] = (mt, db)
            decision = review_data['matches'].get(name, {}).get('state') if name else None
            if not start:
                st, tone = 'scheduled', 'mute'
            elif not post:
                st, tone = 'on field / waiting for score', 'live'
            elif name in sent:
                st, tone = 'sent to YouTube + TBA', 'ok'
            elif decision == 'rejected':
                st, tone = 'rejected - not uploaded', 'bad'
            elif decision == 'pending':
                st, tone = 'waiting for your confirmation', 'wait'
            elif clip:
                st, tone = 'built - uploading / queued', 'busy'
            elif rec_start and start - datetime.timedelta(seconds=season.get('secondsBeforeStart', 4)) < rec_start:
                st, tone = 'before this recording started', 'bad'
            elif name in seen:
                st, tone = 'building clip', 'busy'
            elif (now - post).total_seconds() < 50:
                st, tone = 'score posted - FRUIT waits 50 s', 'wait'
            else:
                st, tone = 'waiting for FRUIT (checks every 100 s)', 'wait'
            v = videos.get(name, {}) if name else {}
            rows.append({'id': mid, 'name': name, 'level': m['tournamentLevel'], 'number': m['matchNumber'],
                         'desc': m.get('description', ''), 'scheduled': hhmm(sched), 'start': hhmm(start), 'post': hhmm(post),
                         'red': [t['teamNumber'] for t in m['teams'] if t['station'].startswith('R')],
                         'blue': [t['teamNumber'] for t in m['teams'] if t['station'].startswith('B')],
                         'status': st, 'tone': tone, 'clip_db': db, 'video_id': v.get('video_id'), 'tba': v.get('tba'),
                         '_start': start.timestamp() if start else None, '_sched': sched.timestamp() if sched else None})
    except Exception as e:
        errors.append(f'FIRST API: {e}')

    rows.sort(key=lambda x: (x['_start'] or x['_sched'] or 9e12, x['level'], x['number']))
    played = [r for r in rows if r['_start']]
    on_field = next((r for r in reversed(played) if not r['post']), None)
    next_up = next((r for r in rows if not r['_start']), None)
    behind = round((played[-1]['_start'] - played[-1]['_sched']) / 60) if played and played[-1]['_sched'] else None

    # ---- recording health ----
    rec = {'path': rec_path, 'exists': bool(rec_path and os.path.exists(rec_path))}
    if rec['exists']:
        size, t = os.path.getsize(rec_path), time.time()
        p = prev_size.get(rec_path)
        rec['size_gb'] = round(size / 1e9, 2)
        if p and t > p[0]:
            rec['mbps'] = round((size - p[1]) * 8 / (t - p[0]) / 1e6, 1)
            rec['growing'] = size > p[1]
        prev_size[rec_path] = (t, size)
        created = datetime.datetime.fromtimestamp(os.path.getctime(rec_path)).astimezone()
        rec['started'] = hhmm(created)
        # a finished file has a duration; a file OBS is still writing doesn't, so use the time since it was created
        dur = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', rec_path], timeout=30).stdout.strip()
        length = float(dur) if re.fullmatch(r'[\d.]+', dur or '') else (now - created).total_seconds()
        live_pos = max(0.0, length - 12)                                    # a few seconds behind the end / live edge
        thumb = os.path.join(CACHE, 'live.jpg')
        if os.path.exists(thumb):
            os.remove(thumb)
        run(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{live_pos:.1f}', '-i', rec_path,
             '-frames:v', '1', '-vf', 'scale=640:-1', thumb], timeout=60)
        rec['thumb_time'] = time.strftime('%H:%M:%S')
        rec['audio_db'] = mean_volume(['-ss', f'{max(0.0, live_pos - 10):.1f}', '-t', '10', '-i', rec_path])
        folder = os.path.dirname(rec_path)
        newer = [f for f in glob.glob(os.path.join(folder, '*.mkv')) if os.path.getctime(f) > os.path.getctime(rec_path) + 5]
        rec['newer_file'] = os.path.basename(max(newer, key=os.path.getctime)) if newer else None
        rec['disk_free_gb'] = round(shutil.disk_usage(folder).free / 1e9, 1)

    running = run(['powershell', '-NoProfile', '-Command',
                   "(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='FRUIT.exe'\" | Where-Object { $_.CommandLine -match 'FRUIT\\.(py|exe)' } | Measure-Object).Count"],
                  timeout=30).stdout.strip() not in ('', '0')

    with lock:
        state.update({
            'updated': time.strftime('%H:%M:%S'), 'errors': errors, 'api_ok': api_ok, 'event': event.get('name') or code,
            'code': code, 'tba_key': cfg.get('TBA', {}).get('eventKey', ''), 'fruit_running': running,
            'fruit': fruit, 'review': review_data,
            'counts': {'scheduled': len(rows), 'played': len(played), 'posted': len([r for r in rows if r['post']]),
                       'seen': len([s for s in seen if s.startswith(code)]), 'built': len([n for n in outputs if n.startswith(code)]),
                       'sent': len([s for s in sent if s.startswith(code)]),
                       'silent': len([r for r in rows if r['clip_db'] is not None and r['clip_db'] < -60])},
            'on_field': on_field, 'next_up': next_up, 'behind_min': behind, 'recording': rec, 'matches': rows,
        })


def collector_loop():
    while True:
        try:
            collect()
        except Exception as e:
            with lock:
                state['errors'] = [f'dashboard: {e!r}']
        time.sleep(15)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FRUIT Dashboard</title><style>
:root{--bg:#f4f5f7;--fg:#16181d;--card:#fff;--line:#dfe2e7;--mute:#6b7280;--ok:#15803d;--bad:#c81e1e;--warn:#b45309;--live:#7c3aed;--busy:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#0e1014;--fg:#e9ebef;--card:#181b21;--line:#2a2f38;--mute:#9aa2ad;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--live:#c4b5fd;--busy:#93c5fd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1280px;margin:0 auto;padding:16px}header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;margin-bottom:12px}
h1{font-size:20px;margin:0}h2{margin:0 0 6px;font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--mute);font-weight:600}
.mute{color:var(--mute)}.small{font-size:12px}.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin-bottom:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.big{font-size:26px;font-weight:700;line-height:1.15}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn,.wait{color:var(--warn)}.live{color:var(--live)}.busy{color:var(--busy)}
.alliance{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.chip{border-radius:6px;padding:1px 7px;font-size:12px;font-weight:600}
.r{background:#fde2e2;color:#9b1c1c}.b{background:#dbe7ff;color:#1e3a8a}
@media (prefers-color-scheme:dark){.r{background:#4c1d1d;color:#fecaca}.b{background:#1e2a4a;color:#c7d7fe}}
.counts{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;text-align:center}.counts b{display:block;font-size:22px}
.thumb{width:100%;border-radius:6px;display:block;background:#000;aspect-ratio:16/9;object-fit:cover}
.alert{border:1px solid var(--bad);color:var(--bad);background:var(--card);border-radius:8px;padding:8px 12px;margin-bottom:8px;font-weight:600}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:6px}.bar>i{display:block;height:100%;background:var(--busy)}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}table{width:100%;border-collapse:collapse}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{font-size:12px;color:var(--mute);font-weight:600}
a{color:var(--busy)}button{font:inherit;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:5px 11px;cursor:pointer}
button.primary{background:var(--busy);border-color:var(--busy);color:#fff}button.danger{color:var(--bad)}
.switch{display:inline-flex;gap:8px;align-items:center;cursor:pointer;font-weight:600}.switch input{width:18px;height:18px}
.review{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(420px,1fr))}.review video{width:100%;border-radius:6px;background:#000;aspect-ratio:16/9;display:block}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
</style></head><body><main>
<header><div><h1 id="ev">FRUIT Dashboard</h1><div class="small mute" id="sub"></div></div><div class="small mute" id="upd"></div></header>
<div id="alerts"></div>
<div class="grid">
 <div class="card"><h2>On field</h2><div id="onfield"></div></div>
 <div class="card"><h2>Next up</h2><div id="next"></div></div>
 <div class="card"><h2>FRUIT right now</h2><div id="now"></div></div>
 <div class="card"><h2>Pipeline</h2><div class="counts" id="counts"></div></div>
</div>
<div class="card" style="margin-bottom:10px"><div class="row" style="justify-content:space-between">
 <label class="switch"><input type="checkbox" id="reviewToggle" onchange="setReview(this.checked)"> Confirm each clip before upload</label>
 <span id="reviewInfo" class="small mute"></span></div><div class="review" id="reviewList"></div></div>
<div class="grid">
 <div class="card"><h2>Recording (live picture)</h2><img class="thumb" id="thumb" alt="latest recorded frame"><div class="small mute" id="thumbcap"></div></div>
 <div class="card"><h2>Recording health</h2><div id="rec"></div></div>
</div>
<div class="tbl"><table><thead><tr><th>Match</th><th>Sched</th><th>Started</th><th>Score posted</th><th>Red</th><th>Blue</th><th>Clip audio</th><th>Status</th><th>Links</th></tr></thead><tbody id="rows"></tbody></table></div>
</main><script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const teams=m=>`<div class="alliance">${m.red.map(t=>`<span class="chip r">${t}</span>`).join('')}${m.blue.map(t=>`<span class="chip b">${t}</span>`).join('')}</div>`;
const label=m=>m.level==='Qualification'?`Qual ${m.number}`:(m.desc||m.id);
const tbaKey=id=>({Q:'qm'+id.slice(1),P:'sf'+id.slice(1)+'m1',M:'sf'+id.slice(1)+'m1',F:'f1m'+id.slice(1)})[id[0]];
const ago=t=>t?Math.round(Date.now()/1000-t)+'s ago':'never';
async function post(path,body){await fetch(path,{method:'POST',body:JSON.stringify(body)});tick();}
function setReview(on){post('/api/review/enabled',{on});}
function decide(match,decision){post('/api/review/decide',{match,decision});}
function approveAll(){document.querySelectorAll('[data-pending]').forEach(e=>decide(e.dataset.pending,'approved'));}
let lastReview='';
async function tick(){
 let d;try{d=await (await fetch('/api/state')).json()}catch(e){$('upd').innerHTML='<span class="bad">dashboard not responding</span>';return}
 const f=d.fruit||{},r=d.recording||{},c=d.counts||{},alerts=[];
 $('ev').textContent=d.event||'FRUIT Dashboard';
 $('sub').innerHTML=`${esc(d.code)} · TBA ${esc(d.tba_key)} · FRUIT ${d.fruit_running?'<span class="ok">open</span>':'<span class="bad">not open</span>'}${f.running?' · <span class="ok">processing</span>':''} · FIRST API ${d.api_ok?'<span class="ok">ok</span>':'<span class="bad">error</span>'}${d.behind_min!=null?` · schedule ${d.behind_min>0?d.behind_min+' min behind':d.behind_min<0?(-d.behind_min)+' min ahead':'on time'}`:''}`;
 $('upd').textContent='updated '+(d.updated||'');
 if(!d.fruit_running)alerts.push('FRUIT is not open.');
 else if(!f.running)alerts.push('FRUIT is open but not processing yet - Bake CONFIG and press Make The Sauce.');
 if(r.exists&&r.growing===false)alerts.push('The recording file stopped growing - is OBS still recording?');
 if(r.exists&&r.audio_db!=null&&r.audio_db<-60)alerts.push('The recording has NO AUDIO - clips will be silent.');
 if(r.newer_file)alerts.push(`OBS is writing a newer file (${r.newer_file}) than FRUIT is using - restart FRUIT and select it.`);
 if(r.path&&!r.exists)alerts.push('The recording file in FRUIT\'s CONFIG does not exist.');
 if(r.disk_free_gb!=null&&r.disk_free_gb<20)alerts.push(`Low disk space: ${r.disk_free_gb} GB free.`);
 (d.errors||[]).forEach(e=>alerts.push(e));
 (f.errors||[]).filter(e=>Date.now()/1000-e.t<900).slice(-3).forEach(e=>alerts.push(`FRUIT ${e.worker} error: ${e.message}`));
 $('alerts').innerHTML=alerts.map(a=>`<div class="alert">${esc(a)}</div>`).join('');
 const of=d.on_field;$('onfield').innerHTML=of?`<div class="big live">${esc(label(of))}</div><div class="small mute">started ${of.start}</div>${teams(of)}`:'<div class="big mute">-</div><div class="small mute">no match running</div>';
 const nx=d.next_up;$('next').innerHTML=nx?`<div class="big">${esc(label(nx))}</div><div class="small mute">scheduled ${nx.scheduled||'?'}</div>${teams(nx)}`:'<div class="big mute">-</div>';
 const sk=f.seek||{},bd=f.build||{},sd=f.send||{};
 $('now').innerHTML=`<div>Checked FIRST: ${sk.last_poll?`<b class="${sk.ok?'ok':'bad'}">${ago(sk.last_poll)}</b>`:'<span class="mute">not yet</span>'}</div>
  <div>Building: ${bd.match?`<b class="busy">${esc(bd.match)}</b> <span class="small mute">${ago(bd.since)}</span>`:'<span class="mute">idle</span>'}</div>
  <div>Sending: ${sd.match?`<b class="busy">${esc(sd.match)}</b> <span class="small mute">${esc(sd.phase)}</span>`:`<span class="mute">${esc(sd.phase||'idle')}</span>`}</div>
  ${sd.match&&sd.phase==='uploading'?`<div class="bar"><i style="width:${Math.round((sd.progress||0)*100)}%"></i></div><div class="small mute">${Math.round((sd.progress||0)*100)}% uploaded</div>`:''}`;
 $('counts').innerHTML=[['played',c.played+'/'+c.scheduled],['seen',c.seen],['built',c.built],['sent',c.sent]].map(([k,v])=>`<div><b>${v}</b><span class="small mute">${k}</span></div>`).join('')+
   `<div style="grid-column:1/-1" class="small">${c.silent?`<span class="bad">${c.silent} silent clip(s)</span>`:'<span class="mute">no silent clips</span>'}</div>`;
 // confirmation
 const rv=d.review||{enabled:false,matches:{}};$('reviewToggle').checked=!!rv.enabled;
 const pend=Object.entries(rv.matches||{}).filter(([k,v])=>v.state==='pending');
 $('reviewInfo').innerHTML=rv.enabled?(pend.length?`${pend.length} waiting · <button class="primary" onclick="approveAll()">Approve all</button>`:'nothing waiting'):'off - FRUIT uploads automatically';
 const sig=JSON.stringify(pend.map(([k])=>k));
 if(sig!==lastReview){lastReview=sig;$('reviewList').innerHTML=pend.map(([k,v])=>`<div class="card" data-pending="${esc(k)}"><b>${esc(v.title)}</b> <span class="small mute">${esc(k)}</span>
   <video src="/file?p=${encodeURIComponent(v.clip)}" controls preload="metadata" style="margin:8px 0"></video>
   <div class="row"><button class="primary" onclick="decide('${esc(k)}','approved')">Approve &amp; upload</button><button class="danger" onclick="decide('${esc(k)}','rejected')">Reject</button></div></div>`).join('');}
 // recording
 $('thumb').src='/thumb.jpg?'+Date.now();$('thumbcap').textContent=r.thumb_time?`grabbed ${r.thumb_time}`:'';
 $('rec').innerHTML=r.exists?`<div><b>${esc((r.path||'').split(/[\\/]/).pop())}</b></div><div>started ${r.started||'?'} · ${r.size_gb} GB</div>
  <div>bitrate ${r.mbps??'…'} Mbps · ${r.growing===false?'<span class="bad">NOT growing</span>':'<span class="ok">growing</span>'}</div>
  <div>audio ${r.audio_db==null?'…':r.audio_db<-60?'<span class="bad">SILENT</span>':'<span class="ok">'+r.audio_db.toFixed(0)+' dB</span>'}</div>
  <div>disk free ${r.disk_free_gb} GB</div>`:'<span class="bad">no recording selected in FRUIT</span>';
 $('rows').innerHTML=(d.matches||[]).map(m=>`<tr><td><b>${esc(label(m))}</b></td><td>${m.scheduled}</td><td>${m.start}</td><td>${m.post}</td>
  <td>${m.red.join(' ')}</td><td>${m.blue.join(' ')}</td><td>${m.clip_db==null?'':m.clip_db<-60?'<span class="bad">silent</span>':m.clip_db.toFixed(0)+' dB'}</td>
  <td class="${m.tone}">${esc(m.status)}</td><td>${m.video_id?`<a target="_blank" href="https://youtu.be/${esc(m.video_id)}">YouTube</a> `:''}${m.tba?`<a target="_blank" href="https://www.thebluealliance.com/match/${esc(d.tba_key)}_${tbaKey(m.id)}">TBA</a>`:''}</td></tr>`).join('');
}
tick();setInterval(tick,4000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        body = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/':
            return self.send(200, PAGE, 'text/html; charset=utf-8')
        if url.path == '/api/state':
            # FRUIT's live status and the confirmation list are read fresh on every refresh (cheap files);
            # the slower checks (FIRST API, recording) come from the 15-second collector
            from TOOLS import review
            with lock:
                snapshot = dict(state)
            snapshot['fruit'] = read_json('log/status.json', {}) or {}
            snapshot['review'] = {'enabled': review.enabled(), 'matches': review.all_matches()}
            return self.send(200, json.dumps(snapshot, default=str), 'application/json')
        if url.path == '/thumb.jpg':
            p = os.path.join(CACHE, 'live.jpg')
            if os.path.exists(p):
                with open(p, 'rb') as f:
                    return self.send(200, f.read(), 'image/jpeg')
        if url.path == '/file':
            # clips for the confirmation step; only .mp4 files inside FRUIT's output folder
            rel = unquote(parse_qs(url.query).get('p', [''])[0])
            full = os.path.realpath(os.path.join(ROOT, rel))
            if full.startswith(os.path.realpath(path_in_root('output')) + os.sep) and full.endswith('.mp4') and os.path.isfile(full):
                return self.send_file(full)
        self.send(404, b'not found', 'text/plain')

    def send_file(self, path):
        ctype = 'video/mp4'
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get('Range', '')
        if rng.startswith('bytes='):
            a, _, b = rng[6:].partition('-')
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if a and b else size - 1
        self.send_response(206 if rng else 200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if rng:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with open(path, 'rb') as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    def do_POST(self):
        from TOOLS import review
        os.chdir(ROOT)
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        if self.path == '/api/review/enabled':
            review.set_enabled(bool(body.get('on')))
        elif self.path == '/api/review/decide':
            review.decide(body.get('match', ''), body.get('decision', ''))
        self.send(200, b'{}', 'application/json')


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows, address reuse lets us bind a port another program is already serving


def start():
    """Start the dashboard in the background (called by FRUIT) on port 8765, or the next free port if another program
    has it (PORT is updated). Returns False if no port was free."""
    global PORT
    for port in range(8765, 8775):
        try:
            server = Server(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    else:
        return False
    PORT = port
    threading.Thread(target=collector_loop, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


if __name__ == '__main__':
    os.chdir(ROOT)
    if not start():
        raise SystemExit('Ports 8765-8774 are all in use.')
    print(f'FRUIT dashboard: http://localhost:{PORT}  (close this window to stop it)')
    while True:
        time.sleep(3600)
