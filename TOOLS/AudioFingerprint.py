import subprocess
import numpy as np
from datetime import timedelta
from scipy.io import wavfile
from scipy.signal import correlate

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi"}

def media_duration(path):
    """Returns the duration of a media file (video/audio) in seconds

    Args:
        path (str): path to file of interest

    Returns:
        duration (float): duration of media file in seconds
    
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    duration = result.stdout.strip()

    if duration and (duration.upper() != "N/A"):
        return float(duration)

    # Fallback for active/incomplete recordings
    result = subprocess.run(
        ["ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time",
        "-of", "csv=p=0",
        path],
        capture_output=True,
        text=True
    )

    return max([float(x) for x in result.stdout.splitlines() if x.strip()])


def extract_audio_from_video(video_path: str, video_crop_start_sec: float = 0, video_crop_end_sec=None, target_sr: int = 11025):
    """Extract mono WAV audio from an video file using ffmpeg.

    Args:
        video_path (str): Path to the input video file.
        video_crop_start_sec (float): seconds into video to start crop
        video_crop_end_sec (float or None): seconds into video to end crop
        target_sr: Desired sample rate for the output WAV file. (11.025 kHz to match start.wav)
    """
    # Find the last dot in the filename
    dot_index = video_path.rfind(".")
    if dot_index == -1:
        raise ValueError("Input file has no extension.")
    extension = video_path[dot_index:].lower()

    # Validate extension
    if extension not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type: {extension}, supported types are: {', '.join(SUPPORTED_EXTS)}")

    # Build .wav output path
    wav_path = video_path[:dot_index] + ".wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ac", "1",
        "-ar", str(target_sr),
        "-vn", "-copyts"]

    if (video_crop_start_sec != 0) or (video_crop_end_sec != None):
        videoFileDuration = media_duration(video_path)

        if (video_crop_start_sec < 0) or (video_crop_end_sec > videoFileDuration):
            raise ValueError("Crop times must be within the duration of the video file.")
        
        if (video_crop_end_sec == None):
            video_crop_end_sec = videoFileDuration

        video_crop_start_str = str(timedelta(seconds=video_crop_start_sec))
        crop_duration_str = str(timedelta(seconds=video_crop_end_sec-video_crop_start_sec))

        cmd.extend(['-ss', video_crop_start_str, '-t', crop_duration_str])
    
    cmd.append(wav_path)

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    return wav_path

def find_sound_timestamp(ref_wav, video_wav, video_crop_start_sec=0, video_crop_end_sec=None):
    """Find the timestamp of a reference sound within a video's audio track.

    Args:
        ref_wav: Path to the reference WAV file containing the sound to find.
        video_wav: Path to the WAV file extracted from the video.
        video_crop_sec: Optional [start, end] seconds to crop the video audio for faster processing.
    
    Returns:
        Timestamp (in seconds) where the reference sound best matches within the video audio.
        Confidence score of the match (0 to 1, higher is better; typically 0.3-0.6).
    """
    # Load reference sound
    sr_ref, ref = wavfile.read(ref_wav)
    ref = ref.astype(np.float32)
    ref /= np.max(np.abs(ref))

    # Load video audio
    sr_vid, vid = wavfile.read(video_wav)
    vid = vid.astype(np.float32)
    vid /= np.max(np.abs(vid))

    # Crop video audio if provided
    if (video_crop_end_sec is not None):
        if video_crop_start_sec < 0 or video_crop_end_sec > len(vid) / sr_vid or video_crop_start_sec >= video_crop_end_sec:
            raise ValueError("Crop times must be within the duration of the video audio.")
        else:
            crop_start_sample = int(video_crop_start_sec * sr_vid)
            crop_end_sample = int(video_crop_end_sec * sr_vid)

            vid = vid[crop_start_sample:crop_end_sample]

    # Ensure sample rates match
    if sr_ref != sr_vid:
        raise ValueError(f"Sample rates differ: {sr_ref} vs {sr_vid}")

    # Cross-correlation
    corr = correlate(vid, ref, mode='valid')
    best_index = np.argmax(corr)
    best_value = corr[best_index]

    # Compute normalization factor for confidence
    ref_energy = np.linalg.norm(ref)
    vid_energy = np.linalg.norm(vid[best_index : best_index + len(ref)])
    confidence = np.sqrt(best_value / (ref_energy * vid_energy))

    # Convert index → seconds
    timestamp_seconds = (best_index / sr_vid) + video_crop_start_sec

    return round(timestamp_seconds,5), round(confidence, 4)