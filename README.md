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
- **Live dashboard** at http://localhost:8765, or the next free port if another program uses it (starts with FRUIT; press "Open Dashboard"). Shows the match on the field, what FRUIT is building and uploading (with upload progress), the health of the recording, and a table of every match with its YouTube and TBA links.
- **Optional clip confirmation**: tick "Confirm each clip before upload" in FRUIT (or flip the switch on the dashboard). Finished clips then wait on the dashboard, where you can watch each one and Approve & upload or Reject it. Untick it and clips upload straight away again.

Plus a few small fixes: "Make The Sauce" can't start the pipeline twice, a failed FIRST check, build or upload is retried (without uploading the same video twice), a TBA error is reported instead of ignored, a broken CONFIG file no longer closes FRUIT, and a fresh install no longer crashes for lack of a CREDENTIALS file.

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
2. Event Info: Enter season year and event code for the event, and pull FMS
3. YouTube Settings: Add your own description, tags, and if desired playlist link. Authenticate your YouTube account
4. Thumbnail Info: Add any image for sponsor logo if desired, enter correct information and test thumbnail
5. Match Timing: Can adjust to be more accurate for event's match timings. Should be fine as is
6. The Blue Alliance: If desired, input info and press "Verify TBA"
7. Video File: If clipping a Twitch stream, test Twitch connection. If clipping YouTube livestream, press the start recording
YouTube livestream button. If clipping a saved video, press select file and select your video.
8. If recording a YouTube livestream, after starting the recording, press select file, and go to TOOLS/recordings and find the mp4 file that is being recorded.
9. Video File: Select the match type of the first match, enter the number of the first match, and enter the timestamp of that match.
Press "Play 4 Seconds" button to test.
10. Video File: Press "Bake Config" and then press "Make The Sauce." check the seen, built, and sent status to make sure it's running!
11. Notes: If recording a YouTube livestream, when clipping new matches as they appear, it will not be done automatically. You must
reenter the match type (if applicable), the match number, and timestamp, then rebake the config and press make the sauce again.
12. Notes: The "Stop Recording YouTube Livestream" button often isn't necessary, it's fine to keep recording the whole time. Use if
a new recording is desired or if you are finished.
13. Notes: Once clipping starts, if the app crashes or is accidentally restarted, the "Load CONFIG" button will bring back your saved info. Press Load CONFIG then scroll down and select the CONFIG file.