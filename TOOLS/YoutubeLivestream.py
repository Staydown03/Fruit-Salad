import requests
import re
import json


def getChannelIDFromHandle(input_str: str) -> str:
    """
    Gets the YouTube channel ID from a handle by parsing the page's HTML.

    Args:
        input_str (str): YouTube handle

    Returns:
        str: YouTube channel ID
    """
    # Normalize input to handle

    handle = (
        input_str if input_str.startswith("@") else "@" + input_str
    )  # Adds @ symbol to inputted username if not present to get full channel ID

    url = f"https://www.youtube.com/{handle}"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to load page for {handle}: {response.status_code}")

    # Try to find the ytInitialData block
    match = re.search(r"var ytInitialData = ({.*?});</script>", response.text)
    if not match:
        raise Exception(f"ytInitialData block not found for handle {handle}")

    try:
        yt_data = json.loads(match.group(1))
        # Traverse down into the right part of the data
        metadata = yt_data["metadata"]["channelMetadataRenderer"]
        return metadata["externalId"]  # this is the UC... channel ID
    except Exception as e:
        raise Exception(f"Failed to parse channel ID from ytInitialData: {e}")
