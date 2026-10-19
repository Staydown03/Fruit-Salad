import google_auth_httplib2
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import googleapiclient.http
import subprocess
import json
import re
import requests
from datetime import datetime
from TOOLS.oauth_cache import cached_credentials, save_credentials

def authenticate_youtube(SCOPES: list=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"], force_login=False):
    """Authenticates a session with YouTube using oauth

    Args:
        SCOPES (list): YouTube Data API scopes.

    Returns:
        youtube : youtube session
    """

    credentials = None if force_login else cached_credentials(SCOPES)
    if credentials is None:
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
        flow.redirect_uri = 'http://localhost:8080/'
        credentials = flow.run_local_server(port=8080, access_type='offline', prompt='consent', timeout_seconds=180,
                                            authorization_prompt_message='Complete YouTube sign-in in your browser.',
                                            success_message='FRUIT sign-in completed. You may close this tab.')
        save_credentials(credentials)

    # Google's helper excludes HTTP 308 from ordinary redirects: resumable
    # uploads use it for "Resume Incomplete", without a Location header.
    transport = googleapiclient.http.build_http()
    transport.timeout = 30
    http = google_auth_httplib2.AuthorizedHttp(credentials, http=transport)
    youtube = googleapiclient.discovery.build("youtube", "v3", http=http)

    return youtube

def upload_video(youtube, media_file:str, request_body:dict, thumbnail: str=None, playlistID:str='', progress=None, on_uploaded=None):
    """Uploads a video to YouTube; uses 1700 quota (1600 upload + 50 thumbnail + 50 playlist)

    Args:
        youtube : youtube session
        media_file (str): path to video file
        request_body (dict): document following YouTube format for upload
        thumbnail (str): path to thumbnail file
        playlistID (str): YouTube playlist ID to add video to (everything after https://www.youtube.com/playlist?list=)
        progress (callable): optional, called with the uploaded fraction (0-1) after each chunk

    Returns:
        responseID : successfully uploaded YouTube video ID
    """

    # Upload the video in 8 MB chunks so progress can be reported
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=googleapiclient.http.MediaFileUpload(media_file, chunksize=8*1024*1024, resumable=True)
    )

    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=3)
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            if progress:
                progress(status.progress())
    
    # Persist the ID before optional metadata calls that can fail independently.
    if on_uploaded:
        on_uploaded(response['id'])
    finish_video(youtube, response['id'], thumbnail, playlistID)
    return response['id']


def finish_video(youtube, video_id, thumbnail=None, playlistID=''):
    """Retry metadata on an existing upload without uploading the video again."""
    if thumbnail != None:
        request = youtube.thumbnails().set(
            videoId=video_id,
            media_body=googleapiclient.http.MediaFileUpload(thumbnail)
        )
        response_thumbnail = request.execute()
    
    if playlistID != '':
        # A previous insert may have succeeded even if its response was lost.
        existing = youtube.playlistItems().list(
            part='id', playlistId=playlistID, videoId=video_id, maxResults=1
        ).execute()
        if existing.get('items'):
            return
        request = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlistID,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        )
        response_playlist = request.execute()
    

def formatYouTubeTitle(matchID:str, event_title:str, year:int, replay:bool=False):
    """
    Provide a human-readable title for match video on YouTube
        * Quals 41 | 2024 FIN Tippecanoe District

    Args:
        matchID (str): match ID
        event_title (str): event title
        year (int): match year
        replay (bool): video is a replay of a previous match
    
    Returns:
        title (str): matches not found in log file

    """

    translateSymbol = {'M': 'Playoffs', 'P': 'Playoffs', 'Q': 'Quals', 'F': 'Finals'}

    if replay:
        return f"{translateSymbol[matchID[0]]} {matchID[1:]}R | {year} {event_title}"
    else:
        return f"{translateSymbol[matchID[0]]} {matchID[1:]} | {year} {event_title}"

def downloadYouTubeClip(url: str, startTimestamp: str, endTimestamp: str, outputFileName: str):
    """
    Downloads a clip of a YouTube video using yt-dlp
        * yt-dlp does not support YouTube livestreams, as it will return a live edge (ignoring the timestamps)

    Args:
        url (str): YouTube video URL
        startTimestamp (str): timestamp to start at (relative to start of video), H:MM:SS format
        endTimestamp (str): timestamp to end at (relative to start of video), H:MM:SS format
        outputFileName (str): location & name of output filepath

    """

    # prepare command
    command = [
        "yt-dlp", "-q", # run yt-dlp in quiet mode
        "--no-playlist", # prevents JSON metadata fetch
        "-f", "bestvideo+bestaudio/best", # download best video and audio quality
        url, # YouTube video URL
        "--download-sections", f"*{startTimestamp}-{endTimestamp}", # timestamp sections to download
        "--force-overwrites", # overwrite existing file
        "--force-keyframes-at-cuts",
        "-o", outputFileName, # output filename
        "--merge-output-format", "mp4",
        "--retries", "5", # retry 5 times on failure
        "--retry-sleep", "2", # wait 2 seconds between retries
    ]

    print(f"Downloading YouTube video {url} clip from {startTimestamp} to {endTimestamp}.")
    
    # run command in terminal
    subprocess.run(command, check=True)

def getYoutubeTimestamps(url):
    """
    Extract the upload timestamp and duration of a YouTube video from its URL.

    Args:
        url (str): The URL of the YouTube video.
    
    Returns:
        datetime: The upload timestamp as a timezone-aware datetime object.
        int: The duration of the video in seconds.
    """
    # Fetch page HTML
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text

    # Extract the ytInitialPlayerResponse JSON blob
    data = json.loads( re.search(r"ytInitialPlayerResponse\s*=\s*({.*?});", html).group(1))

    # Get information from the JSON data
    duration_seconds = int(data.get("videoDetails", {}).get("lengthSeconds"))
    micro = (data.get("microformat", {}).get("playerMicroformatRenderer", {}))

    date = datetime.fromisoformat(micro["uploadDate"].replace("Z", "+00:00"))

    return date, duration_seconds
