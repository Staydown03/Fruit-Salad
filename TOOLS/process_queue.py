import os #file handling
import queue #queues
import time #waiting
import datetime #datetime math
import threading #multiprocess
import subprocess #ffmpeg calls
import math #ceil for Twitch segments
import pytz #timezone handling

from moviepy import VideoFileClip, concatenate_videoclips
from moviepy.audio.fx.AudioFadeIn import AudioFadeIn
#from moviepy.video.fx.MultiplySpeed import MultiplySpeed
#from moviepy.audio.fx.MultiplyVolume import MultiplyVolume
from moviepy.audio.fx.AudioFadeOut import AudioFadeOut

from TOOLS.Twitch import getLatestTwitchVODs
from TOOLS.Twitch import whichVideoContainsTimestamp
from TOOLS.Twitch import downloadTwitchClip

from TOOLS.YouTube import getYoutubeTimestamps
from TOOLS.YouTube import downloadYouTubeClip

from TOOLS.AudioFingerprint import extract_audio_from_video
from TOOLS.AudioFingerprint import find_sound_timestamp

from TOOLS.FMS import getMatchesFromFMS
from TOOLS.FMS import rewrapMatches

from TOOLS.logging import listNotInLog
from TOOLS.logging import match2str

from TOOLS.thumbnails import generateThumbnail
from TOOLS.YouTube import formatYouTubeTitle
from TOOLS.YouTube import upload_video
from TOOLS.TBA import translateMatchString
from TOOLS.TBA import postTheBlueAlliance
from TOOLS import status
from TOOLS import review

# download buffer "constant" (prevents missing the start or end due to livestream delay)
download_buffer = 6

# Define the queues
queue_build = queue.Queue()
queue_send = queue.Queue()

def incrementCountText(textObject):
    textLabel = textObject.text()[0:7]
    value = int(textObject.text()[7:])
    textObject.setText(textLabel+str(value+1))

def process_queue_seek(user_data, stop_event, QLabelCounter, CREDENTIALS):
    """
    Looks for new matches from FMS and adds them to the queue

    Args:
        user_data (dict): user inputs from FRUIT GUI
        stop_event: (bool) or threading.Event(), used to stop processing
        QLabelCounter: PYQT QLabel() to update respective counter (by 1) in GUI
        CREDENTIALS (dict)

    """
    while not stop_event.is_set():
        try:
            # obtain match information from FMS
            if user_data['program'] == 'FRC':
                matchesRaw = getMatchesFromFMS(user_data['season']['year'], user_data['event']['code'], 'FRC', CREDENTIALS['FRC_username'], CREDENTIALS['FRC_key'])
                matches = rewrapMatches(matchesRaw, "FRC", user_data['event']['timezone'])
            elif user_data['program'] == 'FTC':
                matchesRaw = getMatchesFromFMS(user_data['season']['year'], user_data['event']['code'], 'FTC', CREDENTIALS['FTC_username'], CREDENTIALS['FTC_key'])
                matches = rewrapMatches(matchesRaw, "FTC", user_data['event']['timezone'])
        
            # reformat into list and remove ones that are too fresh
            matches_list = [match for match in matches if (datetime.datetime.now(pytz.timezone(user_data['event']['timezone'])) - match['post']).total_seconds() >= 50] # + datetime.timedelta(seconds=7*60*60)

            # determine which matches have not already been processed
            matches_new = listNotInLog('log/seek.txt', matches_list, user_data['event']['code'])

            # sent matches to builder to be generated, add them to log and count
            with open('log/seek.txt', 'a') as file:
                for match in matches_new:
                    match_str = match2str(match, user_data['event']['code'])
                    file.write(match_str+"\n")
                    queue_build.put(match)
                    incrementCountText(QLabelCounter)
                    print('SEEK: '+match_str)
            status.update('seek', ok=True, last_poll=time.time(), ready=len(matches_list), new=[match2str(m, user_data['event']['code']) for m in matches_new])
        except Exception as error:
            # e.g. flaky internet; keep the seek thread alive and try again next round
            print(f'SEEK ERROR (retrying in 100s): {error!r}')
            status.update('seek', ok=False, last_poll=time.time())
            status.error('seek', repr(error))

        # wait a little bit before looking for new matches
        time.sleep(100)

def build_video_moviepy(user_data:dict, secStart:float, secPost:float, outputFilename='output/match.mp4'):
    """
    Creates match video using moviepy from a local file

    Args:
        user_data (dict): user inputs from FRUIT GUI
            - user_data['video']['filePath'] (str): path to local video file
            - user_data['season']['secondsBeforeStart'] (float): seconds to include before match start
            - user_data['season']['secondsOfMatch'] (float): seconds to include of match play
            - user_data['season']['secondsAfterEnd'] (float): seconds to include after match end
            - user_data['season']['secondsBeforePost'] (float): seconds to include before score post
            - user_data['season']['secondsAfterPost'] (float): seconds to include after score post
        secStart (float): seconds into the video that the match starts
        secPost (float): seconds into the video that the scores post
        outputFilename (str): filename to save the output video as

    """
    with VideoFileClip(user_data['video']['filePath']) as video:
        # clip the match and the scores, adding audio fades to taste
        seg_match = video.subclipped(secStart - user_data['season']['secondsBeforeStart'], secStart + user_data['season']['secondsOfMatch'] + user_data['season']['secondsAfterEnd']).with_effects([AudioFadeIn(0.5)])
        #seg_wait = video.subclipped(secStart + user_data['season']['secondsOfMatch'] + user_data['season']['secondsAfterEnd'], secPost - user_data['season']['secondsBeforePost']).with_effects([MultiplyVolume(factor=0), MultiplySpeed(final_duration=3)])
        seg_score = video.subclipped(secPost - user_data['season']['secondsBeforePost'], secPost + user_data['season']['secondsAfterPost']).with_effects([AudioFadeOut(2)])

        # merge together match and scores
        final = concatenate_videoclips([seg_match, seg_score])

        # save the results as a file
        final.write_videofile(outputFilename, audio_codec='aac')

def build_video_ffmpeg(user_data:dict, secStart:float, secPost:float, outputFilename='output/match.mp4'):
    """
    Creates match video using ffmpeg from a local file

    Args:
        user_data (dict): user inputs from FRUIT GUI
            - user_data['video']['filePath'] (str): path to local video file
            - user_data['season']['secondsBeforeStart'] (float): seconds to include before match start
            - user_data['season']['secondsOfMatch'] (float): seconds to include of match play
            - user_data['season']['secondsAfterEnd'] (float): seconds to include after match end
            - user_data['season']['secondsBeforePost'] (float): seconds to include before score post
            - user_data['season']['secondsAfterPost'] (float): seconds to include after score post
        secStart (float): seconds into the video that the match starts
        secPost (float): seconds into the video that the scores post
        outputFilename (str): filename to save the output video as

    """
    input_file = user_data['video']['filePath']

    # Calculate timings
    match_start = secStart - user_data['season']['secondsBeforeStart']
    match_duration = (
        user_data['season']['secondsBeforeStart'] +
        user_data['season']['secondsOfMatch'] +
        user_data['season']['secondsAfterEnd'])
    score_start = secPost - user_data['season']['secondsBeforePost']
    score_duration = user_data['season']['secondsBeforePost'] + user_data['season']['secondsAfterPost']

    # Filepaths
    match_file = 'input/temp/match.mp4'
    score_file = 'input/temp/score.mp4'

    # Extract match segment with audio fades
    subprocess.run([
        'ffmpeg', '-y',
        "-loglevel", "error",
        '-ss', str(match_start),
        '-t', str(match_duration),
        '-i', input_file,
        '-af', f'afade=t=in:st=0:d=0.5,afade=t=out:st={match_duration - 1}:d=1',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        str(match_file)
    ], check=True)

    # Extract score segment with audio fade out
    subprocess.run([
        'ffmpeg', '-y',
        "-loglevel", "error",
        '-ss', str(score_start),
        '-t', str(score_duration),
        '-i', input_file,
        '-af', f'afade=t=in:st=0:d=0.5,afade=t=out:st={score_duration - 2}:d=2',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        str(score_file)], check=True)

    # Concatenate segments
    subprocess.run([
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-f", "concat",
        "-i", "input/temp/concatenate.txt",
        "-c", "copy",
        str(outputFilename)], check=True)
    
    # Clean temp files to prevent using old ones
    if os.path.exists(match_file):
        os.remove(match_file)
    if os.path.exists(score_file):
        os.remove(score_file)

def process_queue_build_live(user_data:dict, stop_event, QLabelCounter, CREDENTIALS:dict):
    """
    Creates match video using Twitch VOD

    Args:
        user_data (dict): user inputs from FRUIT GUI
            - user_data['video']['type'] (str): type of input video ('twitch', 'local', 'local_live', 'youtube_live', 'youtube_video')
            - user_data['video']['twitchUserID'] (str): user id for a Twitch channel
            - user_data['video']['streamDelay'] (float): seconds from event to sever
            - user_data['season']['secondsBeforeStart'] (float): seconds to include before match start
            - user_data['season']['secondsOfMatch'] (float): seconds to include of match play
            - user_data['season']['secondsAfterEnd'] (float): seconds to include after match end
            - user_data['season']['secondsBeforePost'] (float): seconds to include before score post
            - user_data['season']['secondsAfterPost'] (float): seconds to include after score post
            - user_data['video']['adaptiveSyncDelay'] (bool): should audio fingerprinting be used to adjust stream delay
        stop_event: (bool) or threading.Event(), used to stop processing
        QLabelCounter: PYQT QLabel() to update respective counter (by 1) in GUI
        CREDENTIALS (dict): Twitch API credentials
            - match['Twitch_clientID'] (str): Twitch API client id
            - match['Twitch_clientSecret'] (str): Twitch API client secret

    """
    while not stop_event.is_set():
        try:
            # grab a match from the build queue, 30 seconds wait for timeout
            match = queue_build.get(timeout=30)

            # get the latest VODs for a user ID (pagination ignored)
            latest_VODs = getLatestTwitchVODs(CREDENTIALS['Twitch_clientID'], CREDENTIALS['Twitch_clientSecret'], user_data['video']['twitchUserID'])

            # determine which VOD contains the match
            vod = whichVideoContainsTimestamp(latest_VODs, match['start'], match['post'])
            
            # prepare VOD cut start-point
            streamVideoStartSec = ((match['start'] - vod['created_at']).total_seconds() +user_data['video']['streamDelay'] -user_data['season']['secondsBeforeStart']) #add stream delay (time from event to server) & subtract countdown
            if streamVideoStartSec < 0:
                raise ValueError("Negative start time.")

            # how many seconds into the downloaded clip the match starts
            matchStartSec = (streamVideoStartSec - int(streamVideoStartSec)) + user_data['season']['secondsBeforeStart']
            
            # prepare score post times
            postStartSec = (match['post'] - match['start']).total_seconds() + matchStartSec
            postEndDuration = (match['post'] - match['start']).total_seconds() + user_data['season']['secondsAfterPost']
            
            # convert clip timestamps to strings
            startTimestampStr = str(datetime.timedelta(seconds=(int(streamVideoStartSec))-download_buffer))
            endTimestampStr = str(datetime.timedelta(seconds=(math.ceil(streamVideoStartSec+postEndDuration)+download_buffer)))

            # get clip from Twitch that contains both match + its score
            downloadTwitchClip(int(vod['id']), startTimestampStr, endTimestampStr, 'input/temp/twitchClip.mp4')

            # extract audio from the clip and find the exact timestamp of the match start using audio fingerprinting
            if user_data['video']['adaptiveSyncDelay']:
                wav_path = extract_audio_from_video("input/temp/twitchClip.mp4")
                start_sound_sec, start_sound_conf = find_sound_timestamp("start.wav", wav_path, 0, 20)

                if start_sound_conf > 0.2:
                    # prepare match start and post times
                    delayError = round(start_sound_sec - matchStartSec - download_buffer, 5)
                    matchStartSec = start_sound_sec
                    postStartSec = (match['post'] - match['start']).total_seconds() + start_sound_sec

                    print(f"Stream delay of {user_data['video']['streamDelay']:.4} was adjusted by {delayError/2:.4} seconds due to a confidence of {start_sound_conf:.4}")

                    # update stream delay based on audio timestamp for future matches
                    user_data['video']['streamDelay'] += (delayError/2)
                else:
                    # failed to find good sound match, revert to default
                    matchStartSec += download_buffer
                    print(f"Stream delay of {user_data['video']['streamDelay']:.4} was NOT adjusted due to a low confidence of {start_sound_conf:.4}")
            else:
                # how much to trim from the start of the downloaded clip to get to the video start
                matchStartSec += download_buffer

            try:
                # prepare the output filename
                outputFilename = 'output/'+match2str(match, user_data['event']['code'])+'.mp4'
                
                # build the video from the downloaded clip
                if user_data['buildMethod'] == 'moviepy':
                    build_video_moviepy(user_data, matchStartSec, postStartSec, outputFilename)
                elif user_data['buildMethod'] == 'ffmpeg':
                    build_video_ffmpeg(user_data, matchStartSec, postStartSec, outputFilename)
                
                # add the match to the send queue, update count and log
                queue_send.put(match)
                incrementCountText(QLabelCounter)
                print("BUILT: "+match2str(match, user_data['event']['code']))

            except ValueError as errorText:
                print(f'AAAHHHHHHH {errorText}')
                queue_build.put(match)
            
        except queue.Empty:
            continue
        except ValueError:
            print('negative start time, do not retry match')

def process_queue_build_live_local(user_data:dict, stop_event, QLabelCounter, CREDENTIALS:dict):
    """
    Creates match video using local (live) ".mkv" recording

    Args:
        user_data (dict): user inputs from FRUIT GUI
            - user_data['video']['type'] (str): type of input video ('twitch', 'local', 'local_live', 'youtube_live', 'youtube_video')
            - user_data['video']['streamDelay'] (float): seconds from event to sever
        stop_event: (bool) or threading.Event(), used to stop processing
        QLabelCounter: PYQT QLabel() to update respective counter (by 1) in GUI

    """
    # Convert recordingStartTime to datetime object
    recordingStartTime = datetime.datetime.fromisoformat(user_data['video']['recordingStartTime'])

    while not stop_event.is_set():
        try:
            # grab a match from the build queue, 30 seconds wait for timeout
            match = queue_build.get(timeout=30)

            # how many seconds into the recording the match starts
            matchStartSec = (match['start'] - recordingStartTime).total_seconds() + user_data['video']['streamDelay']

            # raise an exception if the start time is negative
            if (matchStartSec - user_data['season']['secondsBeforeStart']) < 0:
                raise ValueError("Negative start time.")

            # extract audio from the clip and find the exact timestamp of the match start using audio fingerprinting
            if user_data['video']['adaptiveSyncDelay']:
                wav_path = extract_audio_from_video(user_data['video']['filePath'], matchStartSec - download_buffer, matchStartSec + 20 + 1)
                start_sound_sec, start_sound_conf = find_sound_timestamp("start.wav", wav_path, 0, 20)

                if start_sound_conf > 0.2:
                    # calculate error and update start seconds
                    delayError = round(start_sound_sec - download_buffer, 5)
                    matchStartSec = matchStartSec + delayError
                    
                    print(f"Stream delay of {user_data['video']['streamDelay']:.4} was adjusted by {delayError/2:.4} seconds due to a confidence of {start_sound_conf:.4}")

                    # update stream delay based on audio timestamp for future matches
                    user_data['video']['streamDelay'] += (delayError/2)
                else:
                    # failed to find good sound match, revert to default
                    print(f"Stream delay of {user_data['video']['streamDelay']:.4} was NOT adjusted due to a low confidence of {start_sound_conf:.4}")

            postStartSec = (match['post'] - match['start']).total_seconds() + matchStartSec

            try:
                # prepare the output filename
                match_str = match2str(match, user_data['event']['code'])
                outputFilename = 'output/'+match_str+'.mp4'
                status.update('build', match=match_str, phase='building', since=time.time())
                
                # build the video from the downloaded clip
                if user_data['buildMethod'] == 'moviepy':
                    build_video_moviepy(user_data, matchStartSec, postStartSec, outputFilename)
                elif user_data['buildMethod'] == 'ffmpeg':
                    build_video_ffmpeg(user_data, matchStartSec, postStartSec, outputFilename)
                
                # add the match to the send queue, update count and log
                queue_send.put(match)
                incrementCountText(QLabelCounter)
                print("BUILT: "+match_str)
                status.update('build', match=None, phase='idle', last=match_str, last_done=time.time())

            except ValueError as errorText:
                print(f'AAAHHHHHHH {errorText}')
                queue_build.put(match)
            
        except queue.Empty:
            continue
        except ValueError:
            print('negative start time, do not retry match')
            status.update('build', match=None, phase='idle', skipped=match2str(match, user_data['event']['code']))
        except Exception as error:
            # e.g. ffmpeg failed reading the live file; retry a few times instead of killing the build thread
            match['retries'] = match.get('retries', 0) + 1
            match_str = match2str(match, user_data['event']['code'])
            status.update('build', match=None, phase='idle')
            status.error('build', f'{match_str}: {error!r}')
            if match['retries'] <= 3:
                print(f"BUILD ERROR (retry {match['retries']}/3 in 30s) {match_str}: {error!r}")
                time.sleep(30)
                queue_build.put(match)
            else:
                print(f"BUILD FAILED, giving up on {match_str}: {error!r}")

def process_queue_build_static(user_data:dict, stop_event, QLabelCounter, matches):
    """
    Creates match video using local file

    Args:
        user_data (dict): user inputs from FRUIT GUI
            - user_data['video']['type'] (str): type of input video ('twitch', 'local', 'youtube_live', 'youtube_video')
            - user_data['video']['streamDelay'] (float): seconds from event to sever
            - user_data['season']['secondsBeforeStart'] (float): seconds to include before match start
            - user_data['season']['secondsOfMatch'] (float): seconds to include of match play
            - user_data['season']['secondsAfterEnd'] (float): seconds to include after match end
            - user_data['season']['secondsBeforePost'] (float): seconds to include before score post
            - user_data['season']['secondsAfterPost'] (float): seconds to include after score post
            - user_data['video']['adaptiveSyncDelay'] (bool): should audio fingerprinting be used to adjust stream delay
        stop_event: (bool) or threading.Event(), used to stop processing
        QLabelCounter: PYQT QLabel() to update respective counter (by 1) in GUI
        matches (list): list of matches from FMS
            - match['start'] (datetime): timestamp of match start
            - match['post'] (datetime): timestamp of scores post

    """
    user_data['video']['streamDelay'] = 0.0

    if user_data['video']['type'] == 'youtube_video':
        user_data['video']['filePath'] = 'input/temp/youtubeClip.mp4'
        videoDate, fileDuration = getYoutubeTimestamps(user_data['video']['URL'])
    else:
        fileDuration = VideoFileClip(user_data['video']['filePath']).duration
    
    fileMatchStart = [match for match in matches if match["id"] == user_data['video']['matchID']][0]['start']
    fileSecStart = (user_data['video']['matchTime'][0]*60)+user_data['video']['matchTime'][1]
    fileTimeStart = fileMatchStart-datetime.timedelta(seconds=fileSecStart)
    fileTimeEnd = fileMatchStart+datetime.timedelta(seconds=fileDuration-fileSecStart)

    while not stop_event.is_set():
        try:
            match = queue_build.get(timeout=30)

            segmentStartDatetime = match['start']-datetime.timedelta(seconds=user_data['season']['secondsBeforeStart'])
            segmentEndDatetime = match['post']+datetime.timedelta(seconds=user_data['season']['secondsAfterPost'])

            if (segmentStartDatetime >= fileTimeStart)*(segmentEndDatetime < fileTimeEnd):
                # determine video timestamps of notable events
                secStart = (match['start'] - fileMatchStart).total_seconds() + fileSecStart + user_data['video']['streamDelay']
                secPost = (match['post'] - fileMatchStart).total_seconds() + fileSecStart + user_data['video']['streamDelay']

                # prepare the output filename
                outputFilename = 'output/'+match2str(match, user_data['event']['code'])+'.mp4'

                if user_data['video']['type'] == 'youtube_video':
                    # download the clip from YouTube
                    startTimestampStr = str(datetime.timedelta(seconds=(int(secStart))-download_buffer))
                    endTimestampStr = str(datetime.timedelta(seconds=(math.ceil(secPost+user_data['season']['secondsAfterPost']))+download_buffer))
                    downloadYouTubeClip(user_data['video']['URL'], startTimestampStr, endTimestampStr, user_data['video']['filePath'])
                    
                    # timing adjustments for the downloaded clip
                    secStart = secStart - int(secStart) + download_buffer
                    secPost = (match['post'] - match['start']).total_seconds() + secStart
                
                # extract audio from the clip and find the exact timestamp of the match start using audio fingerprinting
                if user_data['video']['adaptiveSyncDelay']:
                    if user_data['video']['type'] == 'youtube_video':
                        wav_path = extract_audio_from_video(user_data['video']['filePath'])
                    else:
                        wav_path = extract_audio_from_video(user_data['video']['filePath'], secStart - download_buffer, secStart + 20)
                    
                    start_sound_sec, start_sound_conf = find_sound_timestamp("start.wav", wav_path, 0, 20)

                    if start_sound_conf > 0.2:
                        # calculate error and use it to 
                        delayError = round(start_sound_sec - download_buffer, 5)

                        print(f"Stream delay of {user_data['video']['streamDelay']:.4} was adjusted by {delayError/2:.4} seconds due to a confidence of {start_sound_conf:.4}")

                        # update times of interest
                        secStart += delayError
                        secPost += delayError
                        
                        # update stream delay based on audio timestamp for future matches
                        user_data['video']['streamDelay'] += (delayError/2)
                    else:
                        # failed to find good sound match, don't change timing or delay
                        print(f"Stream delay of {user_data['video']['streamDelay']:.4} was NOT adjusted due to a low confidence of {start_sound_conf:.4}")

                # build the video from the downloaded clip
                if user_data['buildMethod'] == 'moviepy':
                    build_video_moviepy(user_data, secStart, secPost, outputFilename)
                elif user_data['buildMethod'] == 'ffmpeg':
                    build_video_ffmpeg(user_data, secStart, secPost, outputFilename)
                
                # add the match to the send queue, update count and log
                queue_send.put(match)
                incrementCountText(QLabelCounter)
                print("BUILT: "+match2str(match, user_data['event']['code']))
            else:
                print("NOT IN VIDEO: "+match2str(match, user_data['event']['code']))
        
        except queue.Empty:
            continue

def process_queue_send(user_data, stop_event, QLabelCounter, YouTube_Session):
    """
    Send video to YouTube and other services

    Args:
        user_data (dict): user inputs from FRUIT GUI
        stop_event: (bool) or threading.Event(), used to stop processing
        QLabelCounter: PYQT QLabel() to update respective counter (by 1) in GUI
        YouTube_Session

    """
    while not stop_event.is_set():
        try:
            match = queue_send.get(timeout=30)

            matchString = match2str(match, user_data['event']['code'])

            if YouTube_Session != None:
                # generate match thumbnail
                if user_data['program'] == 'FRC':
                    programImagePath = './images/FIRSTRobotics_IconVert_RGB.png'
                elif user_data['program'] == 'FTC':
                    programImagePath = './images/FIRSTTech_IconVert_RGB.png'
                
                if user_data['event']['forceDetails']:
                    thumbnailLoc = generateThumbnail(match, programImagePath, user_data['event']['details'], None)
                elif user_data['event']['logoSponsor'] != None:
                    thumbnailLoc = generateThumbnail(match, programImagePath, None, user_data['event']['logoSponsor'])
                else:
                    thumbnailLoc = generateThumbnail(match, programImagePath, user_data['event']['details'], None)

                title = formatYouTubeTitle(match["id"], user_data['event']['name'], user_data['season']['year']) #FTC FMS doesn't report replay?
                
                request_body = {
                    "snippet": {
                        "title": title,
                        "description": user_data['YouTube']['description'],
                        "categoryId": "28",  # Category ID for "Science & Technology"
                        "tags": user_data['YouTube']['tags'].split(',') + [user_data['event']['code'], str(user_data['season']['year']), match["id"], "FRUIT_BCC"] + [user_data['program'], {'FRC':'FIRST Robotics Competition', 'FTC':'FIRST Tech Challenge'}[user_data['program']]]
                    },
                    "status": {
                        "privacyStatus": "unlisted"
                    }
                }

                # optional confirmation of the clip before uploading (switchable at any time)
                if 'videoID' not in match and review.enabled():
                    decision = review.state(matchString)
                    if decision is None:
                        review.submit(matchString, 'output/'+matchString+'.mp4', title)
                        status.update('send', match=None, phase='waiting for confirmation')
                        print("WAITING FOR CONFIRMATION: "+matchString)
                    if decision == 'rejected':
                        print("REJECTED, not uploaded: "+matchString)
                        continue
                    if decision != 'approved':
                        queue_send.put(match)
                        time.sleep(3)
                        continue

                # remember the video ID so a retry (e.g. TBA failed) doesn't upload the match twice
                if 'videoID' not in match:
                    status.update('send', match=matchString, phase='uploading', progress=0.0, since=time.time())
                    match['videoID'] = upload_video(YouTube_Session, 'output/'+matchString+'.mp4', request_body, thumbnailLoc, user_data['YouTube']['playlist'],
                                                    progress=lambda p: status.update('send', progress=p))
                    status.record_video(matchString, video_id=match['videoID'], title=title, tba=False)
                videoID = match['videoID']
                print(f"UPLOADED: {matchString} -> https://youtu.be/{videoID}")

                if (user_data['program'] == 'FRC') and (user_data['TBA']['eventKey'] != ''):
                    status.update('send', match=matchString, phase='linking on TBA')
                    data = {translateMatchString(match['id']): videoID}
                    response = postTheBlueAlliance(user_data['TBA']['Auth_Id'], user_data['TBA']['Auth_Secret'], user_data['TBA']['eventKey'], data)
                    if response.status_code != 200:
                        raise RuntimeError(f'TBA returned {response.status_code}: {response.text[:200]}')
                    status.record_video(matchString, tba=True)
            
            with open('log/send.txt', 'a') as file:
                file.write(matchString+"\n")
            incrementCountText(QLabelCounter)
            print("SENT: "+matchString)
            status.update('send', match=None, phase='idle', last=matchString, last_done=time.time())

        except queue.Empty:
            continue
        except Exception as error:
            # e.g. upload dropped on event wifi; keep the send thread alive and retry
            status.update('send', match=None, phase='waiting to retry')
            status.error('send', f'{matchString}: {error!r}')
            match['retries_send'] = match.get('retries_send', 0) + 1
            if match['retries_send'] <= 5:
                print(f"SEND ERROR (retry {match['retries_send']}/5 in 60s) {matchString}: {error!r}")
                time.sleep(60)
                queue_send.put(match)
            else:
                print(f"SEND FAILED, giving up on {matchString}: {error!r}")