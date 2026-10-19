import requests
import hashlib
import json

def postTheBlueAlliance(TBA_Auth_Id:str, TBA_Auth_Secret:str, TBA_eventKey:str, data={}, TBA_Endpoint="/event/{eventKey}/match_videos/add"):
    """Pushes data to The Blue Alliance (TBA) using their write API

    Args:
        TBA_Auth_Id (string): X-TBA-Auth-Id provided by TBA for your event 
        TBA_Auth_Secret (string): X-TBA-Auth-Secret provided by TBA for your event
        TBA_eventKey (string): TBA event key for your event
        data (dict): data structure in according to your TBA write API endpoint; match_videos example: {'q44':'dQw4w9WgXcQ'}
        TBA_Endpoint (string): TBA write API endpoint, include {eventKey}

    Returns:
        response (requests.response)

    """

    # generate the whole API endpoint
    endpoint = '/api/trusted/v1'+TBA_Endpoint.replace('{eventKey}', TBA_eventKey)

    # Sign exactly the bytes sent; do not separately reconstruct a JSON body.
    body = json.dumps(data, ensure_ascii=True).encode('utf-8')
    postHash = hashlib.md5((TBA_Auth_Secret + endpoint).encode('utf-8') + body).hexdigest()
    headers = {
        "X-TBA-Auth-Id": TBA_Auth_Id,
        "X-TBA-Auth-Sig": postHash,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.post('https://www.thebluealliance.com'+endpoint, headers=headers,
                             data=body, timeout=(10, 30), allow_redirects=False)

    return response


def require_tba_success(response):
    """HTTP 200 alone does not prove a TBA API operation was accepted."""
    if response.status_code != 200:
        raise RuntimeError(f'TBA rejected the link (HTTP {response.status_code}). Check the event key and write credentials.')
    try:
        result = response.json()
    except (ValueError, AttributeError):
        raise RuntimeError('TBA returned no JSON confirmation. The link was not marked completed; check TBA before retrying.') from None
    if not isinstance(result, dict) or result.get('Error') or not result.get('Success'):
        raise RuntimeError('TBA did not confirm success. The link was not marked completed; check TBA before retrying.')


def translateMatchString(matchID):
    """translate my match string to what TBA is expecting

    Examples:
        Q44 -> qm44 (qm#)
        P3 -> sf3m1 (sf#m3)
        M6 -> sf6m1 (sf#m1)
        F3 -> f1m3  (f1m#)

    Args:
        matchID (string): match ID using my format

    Returns:
        matchString (string): match string in TBA format

    """
    if matchID[0] == 'Q':
        return 'qm'+matchID[1:]
    elif matchID[0] == 'P':
        return 'sf'+matchID[1:]+'m1'
    elif matchID[0] == 'M':
        return 'sf'+matchID[1:]+'m1'
    elif matchID[0] == 'F':
        return 'f1m'+matchID[1:]
    else:
        raise AttributeError('matchID does not start with one of [Q, P, M, F]')
