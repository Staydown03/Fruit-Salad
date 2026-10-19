# FRUIT = FIRST Robotics Uploader from an Indiana Teammate
A python script (with GUI) for the automated processing of (long) livestreams into (short) match videos.

![FRUIT Logo: a triangular apple, a circular pineapple, and a square blueberry](./images/icon_FRUIT.svg)

## How it works
1. Gets information about the matches from FIRST, includes start time and score post time
2. Splits the livestream recording into chucks based on those start & post times
3. Combines those chunks together into match videos
4. Generates a thumbnail using the match number and teams involved
5. Uploads the videos to YouTube
6. Notifies The Blue Alliance of the videos

## Added in this version
This is [FRUIT](https://github.com/BrysonC/FRUIT) by Bryce Castle with two additions:
- **Live dashboard** at http://localhost:8765, or the next free port if another program uses it (starts with FRUIT; press "Open dashboard"). Shows the match on the field, what FRUIT is building and uploading (with upload progress), the health of the recording, and a table of every match with its YouTube and TBA links.
- **Optional clip confirmation**: tick "Confirm each clip before upload" in FRUIT (or flip the switch on the dashboard). Finished clips then wait on the dashboard, where you can watch each one and Approve & upload or Reject it. Untick it and clips upload straight away again.

Plus a few small fixes: "Make the Sauce" can't start the pipeline twice, a failed FIRST check, build or upload is retried (without uploading the same video twice), a TBA error is reported instead of ignored, a broken CONFIG file no longer closes FRUIT, and a fresh install no longer crashes for lack of a CREDENTIALS file.

## Getting FRUIT running (FRUIT.exe, no Python needed)
1. Download `FRUIT-windows.zip` from the [Releases](../../releases) page and unzip it anywhere
2. FRUIT uses the ffmpeg already on your PC (on PATH or installed with winget); if there is none, it offers to install it with `winget install Gyan.FFmpeg`
3. Put your Google OAuth client file in the FRUIT folder as `client_secret.json` (see below)
4. Run `FRUIT.exe`

## Getting FRUIT running (from source)
1. Install Python 3.12 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH")
2. Run `setup.bat`; it creates `.venv`, installs the packages in requirements.txt and installs ffmpeg with winget
3. Put your Google OAuth client file in the FRUIT folder as `client_secret.json` (see below)
4. Start FRUIT with `Start FRUIT.bat`
5. Optional: run `build_exe.bat` to build your own `dist\FRUIT\FRUIT.exe`

## Your keys (never commit these)
FRUIT keeps everything private in its own folder, and `.gitignore` keeps it out of git:
- `CREDENTIALS`: FIRST API username + key (and Twitch / FTC if used). Created empty on first start; fill it in with the credentials button in FRUIT. Register at https://frc-events.firstinspires.org/services/api
- `youtube_token.json`: saved YouTube OAuth login; sensitive and git-ignored. Backups are kept in `log/oauth-backups/` before replacement. Never share token files or these backups.
- `client_secret.json`: Google Cloud Console → APIs & Services → enable "YouTube Data API v3" → Credentials → Create OAuth client ID → "Desktop app" → download the JSON. `client_secret.example` shows its shape. While the OAuth app is in testing, add your YouTube account as a test user.
- `CONFIG` / `*.CONFIG`: your saved event settings, including your TBA Auth ID and secret (request them at https://www.thebluealliance.com/request/apiwrite)

## Setup for Developers; Operating FRUIT
1. Follow https://github.com/purduefirst/FRUIT/wiki/APIs and register for desired API keys
2. If livestreaming through Twitch, obtain Twitch Client ID and Client Secret
3. If livestreaming through YouTube, obtain Youtube API Key and Channel ID
4. Fill empty credentials fields with API information; in FRUIT or in the code
5. Input correct Season Year and Event Code in the event info tab of FRUIT; no event name needed
6. Once YouTube livestream is being recorded, the MP4 being recorded to can be used as a static video

## Guide for use
1. Welcome page: select correct program and enter and save all necessary credentials. Enter YouTube Username and copy + paste the channel ID if you plan to record and clip a YouTube livestream
2. Event information: Enter season year and event code for the event, and pull FMS
3. YouTube settings: Add your own description, tags, and if desired playlist link. Authenticate your YouTube account
4. Thumbnail settings: Add any image for sponsor logo if desired, enter correct information and test thumbnail
5. Match timing: Can adjust to be more accurate for event's match timings. Should be fine as is
6. The Blue Alliance: If desired, input info and press "Verify TBA"
7. Video File: If clipping a Twitch stream, test Twitch connection. If clipping YouTube livestream, press the start recording
YouTube livestream button. If clipping a saved video, press select file and select your video.
8. If recording a YouTube livestream, after starting the recording, press select file, and go to TOOLS/recordings and find the mp4 file that is being recorded.
9. Video File: Select the match type of the first match, enter the number of the first match, and enter the timestamp of that match.
Press "Play 4 Seconds" button to test.
10. Video File: Press "Bake Config" and then press "Make the Sauce." check the seen, built, and sent status to make sure it's running!
11. Notes: If recording a YouTube livestream, when clipping new matches as they appear, it will not be done automatically. You must
reenter the match type (if applicable), the match number, and timestamp, then rebake the config and press make the sauce again.
12. Notes: The "Stop Recording YouTube Livestream" button often isn't necessary, it's fine to keep recording the whole time. Use if
a new recording is desired or if you are finished.
13. Notes: Once clipping starts, if the app crashes or is accidentally restarted, the "Load CONFIG" button will bring back your saved info. Press Load CONFIG then scroll down and select the CONFIG file.
## Reliability and recovery

- FIRST and TBA requests have connection/read timeouts. FIRST polling retries after
  100 seconds; the dashboard flags a worker check older than 240 seconds.
- Recording preview and audio checks run independently of dashboard event collection.
  Preview extraction has a 20-second timeout and waits 30 seconds between media cycles
  (audio checks add time). Failed attempts retain the last successful picture and its age.
- A new preview is published only after a complete JPEG is available. The browser loads
  replacements before displaying them, and only requests a new picture when it changes.
- Audio warnings describe a recent quiet sample rather than claiming the whole recording
  has no audio. Match audio checks sample the first 30 seconds in a separate worker, checking the
  oldest unchecked clip first. Successful levels are cached in `.cache/clip-audio.json`
  across restarts; changed clips are checked again. Pending/failed checks are labeled,
  and failed checks retry after 60 seconds without holding up other clips.
- "Awaiting results" replaces "On field": FIRST's public API is not a reliable live
  field-status source. Upcoming matches are populated from the published schedule.
- YouTube IDs are saved immediately after upload acceptance, before thumbnail, playlist,
  and TBA work. On restart, saved uploads resume their remaining steps without rebuilding
  or uploading the video again. Keep `log/videos.json` along with `log/send.txt`.
  If an upload response is lost before its ID can be saved, check YouTube for duplicates.
- Built match MP4s in `output/` survive restarts and are reused after their video
  stream is readable and its duration is at least the configured match duration
  (`secondsOfMatch`). There is no maximum duration or required pre/post padding.
  Live local-file recovery checks the MP4 before accessing the OBS recording or
  running audio sync. Missing, unreadable or shorter-than-match clips are rebuilt;
  `.pending.mp4` files are never reused. Keep the `output/` folder and event logs.
  To intentionally regenerate an otherwise valid clip (for example, after adjusting
  sync), move its MP4 out of `output/` while FRUIT is closed. Completed entries in
  `log/send.txt` are still skipped; back up logs before manually changing them.
- FFmpeg match builds have a 15-minute timeout per subprocess. Final MP4s are checked for
  readable video and at least the configured match duration before replacing the published clip. Audio sync
  probes also have timeouts. OBS split recordings still require manual file selection;
  footage spanning two files is not joined automatically.

Apply source updates by restarting FRUIT when current uploads have finished. A packaged
`FRUIT.exe` must be rebuilt to include source changes. No OBS restart is required.

Offline regression checks (no credentials or event logs are used):

```text
python -m unittest discover -s tests -v
node tests/dashboard.test.cjs
```


## Utilities: link manually uploaded videos to TBA

1. Start FRUIT and load your event CONFIG, or fill in Event information and The Blue Alliance
   tabs. This utility uses the TBA event write Auth ID/Secret; no Google login or
   YouTube API key is required. Use Utilities before starting Make the Sauce.
2. Open **Utilities**. Load local matches and enter their YouTube URLs, add rows,
   or paste one match/URL pair per line. Examples (replace the video ID):

   ```text
   Q1 https://youtu.be/VIDEO_ID
   P9 https://www.youtube.com/watch?v=VIDEO_ID
   NJNOR_P9_1633.mp4 https://youtu.be/VIDEO_ID
   ```

   Exact TBA match keys (`qm1`, `sf9m1`, `f1m2`), YouTube short/live/embed URLs,
   and raw 11-character video IDs also work. Use a full local clip filename if a
   match has multiple attempts. Duplicate match destinations in one batch are rejected.
3. Select rows by clicking, Shift-clicking a range, Ctrl-clicking individual rows,
   or using **Select all rows** / Ctrl+A. **Check selected** and **Uncheck selected**
   change which selected rows will be linked. **Remove selected rows** removes only
   the highlighted table rows, without deleting videos or changing existing TBA links.
   Double-click a match/URL cell to edit it.
4. Check the rows to send, press **Validate checked mappings**, review the target
   event and the normalized match keys, then press **Link checked videos to TBA**.
   Each row reports its result; failed rows remain checked for a later retry. Success
   requires TBA's JSON confirmation, not just HTTP 200. Public match pages may still
   serve cached content; open the match URL with a new query string (for example,
   `?refresh=1`, then a different value on a later check) to request a fresh page.
5. By default, matching local clips are marked completed only after TBA accepts
   their link, so later processing skips them. Existing processing logs are backed
   up under `log/manual-link-backups/` before modification. Uncheck this option for
   TBA-only updates. Rows without a matching local record explicitly say "TBA link only".
   This utility adds links; it does not delete previously linked videos.

## Remembering YouTube sign-in

**Connect to YouTube** now reuses `youtube_token.json`, refreshing expired access
credentials when possible. The first connection still opens Google's browser sign-in.
**Use another Google account** forces a new sign-in. Reconnect/switch before starting
Make the Sauce. Saved credentials remain local to the FRUIT folder and are excluded
from Git; no token is put in CONFIG.

An API key cannot authorize YouTube uploads. Google may require reauthorization if
consent expires or is revoked. External OAuth apps in Testing generally receive
refresh tokens expiring after seven days. An Internal audience requires a Google
Workspace/Cloud Identity organization and a project owned by that organization;
using the same personal Google account for the channel and project does not qualify.

References: [YouTube authorization](https://developers.google.com/youtube/data/guides/authentication),
[Google refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration),
[Internal/personal-use verification exceptions](https://support.google.com/cloud/answer/13464323).
