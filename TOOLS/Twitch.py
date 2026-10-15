import requests
import os
import subprocess
import datetime
import yt_dlp

def getTwitchAuthHeader(client_id:str, client_secret:str):
    """
    Retrieves the access token for the Twitch API.

    Args:
        client_id (str): Your Twitch client ID.
        client_secret (str): Your Twitch client secret.

    Returns:
        dict: header for use in requests.get for Twitch
    
    Raises:
      Exception: Unable to obtain Twitch access token
    """
    
    params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    
    response = requests.post("https://id.twitch.tv/oauth2/token", data=params)

    if response.status_code == 200:
        return {'Client-ID': client_id, 'Authorization': f'Bearer {response.json()['access_token']}'}
    else:
        raise Exception(f"Error: {response.status_code}, {response.text}")


def getTwitchVideoData(client_id:str, client_secret:str, vod_id:int):
    """
    Retrieves the access token for the Twitch API.

    Args:
        client_id (str): Your Twitch client ID.
        client_secret (str): Your Twitch client secret.
        vod_id (int): Twitch VOD ID

    Returns:
        dict: information about the video
    """

    # obtain data about VOD
    headersTwitchAPI = getTwitchAuthHeader(client_id, client_secret)
    response = requests.get('https://api.twitch.tv/helix/videos?id='+str(vod_id), headers=headersTwitchAPI)

    return response.json()['data'][0]

def covertID2Username(client_id:str, client_secret:str, username:int):
    """
    Retrieves the associated user ID provided a Twitch username

    Args:
        client_id (str): Your Twitch client ID.
        client_secret (str): Your Twitch client secret.
        username (str): Twitch username

    Returns:
        user_id (str): Twitch user ID
    """
        
    headersTwitchAPI = getTwitchAuthHeader(client_id, client_secret)
    user_response = requests.get('https://api.twitch.tv/helix/users?login='+username, headers=headersTwitchAPI)
    user_data = user_response.json()
    user_id = user_data['data'][0]['id']

    return user_id

def getLatestTwitchVODs(client_id:str, client_secret:str, user_id:str):
    """
    Retrieves the associated user ID provided a Twitch username

    Args:
        client_id (str): Your Twitch client ID.
        client_secret (str): Your Twitch client secret.
        user_id (str): Twitch user ID

    Returns:
        vods_data (list): list of VOD information
    """
        
    headersTwitchAPI = getTwitchAuthHeader(client_id, client_secret)
    vods_url = f'https://api.twitch.tv/helix/videos?user_id={user_id}'
    vods_response = requests.get(vods_url, headers=headersTwitchAPI)
    vods_data = vods_response.json()['data']

    # covert information into more useable form
    for vod in vods_data:
        vod['duration'] = durationStr2Sec(vod['duration'])
        vod['created_at'] = datetime.datetime.fromisoformat(vod['created_at'].replace("Z", "+00:00"))
        vod['published_at'] = datetime.datetime.fromisoformat(vod['published_at'].replace("Z", "+00:00"))

    return vods_data

def whichVideoContainsTimestamp(vod_list:list, startTimestamp:datetime.datetime, endTimestamp:datetime.datetime):
    """
    Sorts through a list of Twitch VODs and returns which VOD contains both the start and end timestamps

    Args:
        vod_list (list): list of VOD data (dict) information from Twitch API
            - vod['created_at'] (datetime): timestamp that VOD was created at
            - vod['duration'] (int): duration of VOD in seconds
        startTimestamp (datetime): start timestamp of interest
        endTimestamp (datetime): end timestamp of interest
    
    Returns:
        vod (dict): 

    """
    # review VODs from oldest to newest
    for vod in reversed(vod_list):
        # check for timestamps in the vod (bool)
        startInVideo = (startTimestamp - vod['created_at']).total_seconds() < vod['duration']
        endInVideo = (endTimestamp - vod['created_at']).total_seconds() < vod['duration']

        if startInVideo and endInVideo:
            # video is in the same VOD
            return vod
        elif startInVideo ^ endInVideo:
            # video is in different VODs (XOR)
            raise Exception("The match is split across multiple Twitch VODs")
        
    # video not found
    raise Exception("There is no Twitch VOD for the provided timestamps")

def downloadTwitchClip_streamlink(vod_id: int, startTimestamp: str, durationSeconds: str, outputFileName: str):
    """
    OLD: Downloads a clip of a Twitch VOD using streamlink, be wary of weird timestamps
        * VODs are broken into 10 second segments (m3u8 process)
        * segments are from XX:X1 to XX:X1 + 9.999 but return XX:XX to XX:XX + 10 ¯\\_(ツ)_//¯

    Args:
        vod_id (int): twitch VOD ID
        startTimestamp (str): timestamp to start at (XX:XX)
        durationSeconds (str): duration (XX:XX)
        outputFileName (str): location & name of output filepath

    """
    # delete file if it already exists
    try:
        os.remove(outputFileName)
    except OSError:
        pass
    
    # prepare command
    command = [
        'streamlink',
        "https://www.twitch.tv/videos/"+str(vod_id),
        'best',
        '--hls-start-offset', startTimestamp,
        '--hls-duration', durationSeconds,
        '-o', outputFileName,
        '--hls-live-edge', '1'
    ]
    
    # run command in terminal
    subprocess.run(command)

def downloadTwitchClip(vod_id: int, startTimestamp: str, endTimestamp: str, outputFileName: str):
    """
    Downloads a clip of a Twitch VOD using yt-dlp, be wary of weird timestamps
        * VODs are broken into 10 second segments (m3u8 / HLS process)

    Args:
        vod_id (int): twitch VOD ID
        startTimestamp (str): timestamp to start at (relative to start of VOD), H:MM:SS format
        endTimestamp (str): timestamp to end at (relative to start of VOD), H:MM:SS format
        outputFileName (str): location & name of output filepath

    """

    # prepare command
    command = [
        "yt-dlp", "-q", # run yt-dlp in quiet mode
        "--no-playlist", # prevents JSON metadata fetch
        "-f", "bestvideo+bestaudio/best", # download best video and audio quality
        "https://www.twitch.tv/videos/"+str(vod_id), # Twitch VOD URL
        "--download-sections", f"*{startTimestamp}-{endTimestamp}", # timestamp sections to download
        "--force-overwrites", # overwrite existing file
        "--force-keyframes-at-cuts", # get around Twitch's weird segmenting
        "-o", outputFileName, # output filename
        "--merge-output-format", "mp4"
    ]

    print(f"Downloading Twitch VOD {vod_id} clip from {startTimestamp} to {endTimestamp}.")
    
    # run command in terminal
    subprocess.run(command)

def durationStr2Sec(duration):
    """
    translates duration in string format to integer

    Args:
        duration (str): duration in XhXXmXXs format

    Returns:
        total_seconds (int): duration in seconds
    """

    # Initialize total seconds to 0
    total_seconds = 0
    
    # Split the duration into parts based on 'h', 'm', and 's'
    if 'h' in duration:
        hours, duration = duration.split('h')
        total_seconds += int(hours) * 3600
    if 'm' in duration:
        minutes, duration = duration.split('m')
        total_seconds += int(minutes) * 60
    if 's' in duration:
        seconds = duration.split('s')[0]
        total_seconds += int(seconds)

    return total_seconds