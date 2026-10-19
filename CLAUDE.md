# CLAUDE.md

Guidance for Claude (or any AI coding assistant) helping someone set up and run FRUIT. Most of the work is getting
the credentials and APIs right; walk the user through the sections below one service at a time, and check each one
works before moving on.

FRUIT (fork of https://github.com/BrysonC/FRUIT) is a Windows PyQt6 app that cuts an event recording into one video
per match: FIRST Events API (match times) → ffmpeg (clip) → YouTube (upload) → The Blue Alliance (link the video).
This fork adds a live dashboard and an optional "confirm each clip before upload" step (see README.md).

## Ground rules for secrets
- Secret files live only in the FRUIT folder and are git-ignored: `CREDENTIALS`, `client_secret.json`,
  `CONFIG` / `*.CONFIG`, `youtube_token.json`, `log/`. Never commit them, and never echo their values into chat, commits, issues or logs.
- Before overwriting or deleting any of them, copy it somewhere safe and check the copy isn't empty.
- Before any `git push`, scan `git diff --cached` for keys, tokens, emails and personal paths (e.g. `C:\Users\<name>`).
- The user signs in to Google / FIRST / TBA themselves. Don't ask for their passwords; ask them to paste only the
  specific key, or better, to type it into FRUIT's own fields.

## 1. Install
- From source: Python 3.12+ → `setup.bat` (creates `.venv`, installs requirements, installs ffmpeg with winget only if
  `where ffmpeg` finds nothing) → `Start FRUIT.bat`.
- Packaged: unzip FRUIT.exe's folder and run `FRUIT.exe`; it offers to install ffmpeg only if none is found.
- FRUIT works from its own folder (relative paths); the .bat and exe set this up.

## 2. FIRST Events API (required) → `CREDENTIALS`
1. Register at https://frc-events.firstinspires.org/services/api (FTC: https://ftc-events.firstinspires.org/services/API).
   The username is what they chose; the authorization token (a GUID) arrives by email.
2. In FRUIT: "API credentials" → FRC API Username + FRC API AuthorizationKey → Save and close.
   This writes `CREDENTIALS` (JSON; FRUIT creates an empty one on first start).
3. Check: Event information tab → season + **FIRST** event code (the short code shown on frc-events.firstinspires.org, not the TBA key)
   → "Load event data". The event name filling in means the key works. A 401 means wrong username/token; "no matches"
   before the event starts is normal (the schedule appears once FMS publishes it).

## 3. YouTube (required for uploads) → `client_secret.json`
1. https://console.cloud.google.com → create a project.
2. APIs & Services → Library → enable **YouTube Data API v3**.
3. OAuth consent screen (Google Auth Platform): user type **External**, fill in app name + emails, and under
   **Audience / Test users** add the Google account that owns the YouTube channel. Leaving the app in "Testing" is fine.
4. Credentials → Create credentials → **OAuth client ID** → application type **Desktop app** → download the JSON.
   (If the console only offers "Create client", that's the same flow in the newer UI.)
5. Save it in the FRUIT folder as exactly `client_secret.json` (`client_secret.example` shows the shape).
6. In FRUIT: YouTube tab → "Connect to YouTube" → browser sign-in. Pick the channel's account; on "Google hasn't
   verified this app" choose Advanced → continue (it's their own app). Scopes: youtube.upload + youtube.
   The sign-in uses http://localhost:8080, so that port must be free. FRUIT saves the OAuth session in
   git-ignored `youtube_token.json` and refreshes it when possible; use Connect to YouTube after restarting.
   Old tokens are backed up under `log/oauth-backups/` before replacement. Google can still require new consent
   (External apps in Testing generally expire refresh tokens after seven days). API keys cannot authorize uploads.
7. Quota: uploads are expensive in YouTube API quota. Check APIs & Services → YouTube Data API v3 → Quotas before
   a big event and request an increase if needed.
- Optional `Youtube_API_Key` (in CREDENTIALS) is only for recording a YouTube livestream; create an API key under
  Credentials. Twitch Client ID/Secret only for the Twitch source (https://dev.twitch.tv/console).

## 4. The Blue Alliance (optional, links videos to matches)
1. Request write keys for the event at https://www.thebluealliance.com/request/apiwrite (must be logged in to TBA,
   and usually be an event organizer/AV volunteer). TBA emails/shows an **Auth ID** and **Auth Secret** per event.
2. In FRUIT: TBA tab → TBA event key (e.g. `2026abcd`, year + code as on thebluealliance.com) + Auth ID + Auth Secret
   → "Verify TBA" ("TBA API Verified!" means the keys work).
3. These are saved into the baked `CONFIG`, so treat CONFIG files as secret too.

## 5. Run the event
1. Record with OBS (HDMI capture) to .mkv. FRUIT: Video Source → "Live" + "Local File" → select the growing file.
2. Fill the tabs, "Bake CONFIG", then "Make the Sauce" **once**. Watch the dashboard (http://localhost:8765, or the
   next free port; "Open dashboard" button). Optional: tick "Confirm each clip before upload".
3. To change settings or switch to a new recording file: close FRUIT, start it, "Load CONFIG", edit, bake, sauce.

## Troubleshooting from real events
- FRUIT closes when loading a CONFIG → hand-edited Windows path with single `\`; use `\\` or `/` (this fork now
  shows "file is not valid" instead of closing).
- Clips shifted by several seconds → "Adaptive audio timestamp sync" matched the wrong sound (silent/bad game audio);
  untick it.
- Gradual audio drift over hours → an OBS setup issue (e.g. Desktop Audio capturing a monitored source), not FRUIT.
- A match listed in `log/send.txt` is never uploaded again; remove that line (FRUIT closed) to redo it.
- `log/status.json` and the dashboard's error list show the latest worker errors.
