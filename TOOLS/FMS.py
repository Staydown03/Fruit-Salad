import json         # response handling
import requests     # API data request
import base64       # API hashing
import datetime     # str conversion
import pytz     # apply timezone

translateSymbol = {'Q': 'Quals', 'P': 'Playoffs', 'F': 'Finals'}

# CREDENTIALS (dict): credentials from https://frc-events.firstinspires.org/services/api, contains "FRC_username" and "FRC_key" entries
with open("CREDENTIALS", "r") as file:
    CREDENTIALS = json.load(file) # contains username + authKey

def prepareHeadersFMS(username, authKey):
    """Prepares request header for FMS, allows for authentication

    Args:
        username (str): username for frc-events.firstinspires.or or ftc-events.firstinspires.org
        authKey (str): authKey provided from related service

    Returns:
        headers (dict): header for use in requests.get for FMS

    """
    AuthorizationToken = (username+':'+authKey).encode("ascii")
    Authorization = base64.b64encode(AuthorizationToken).decode("ascii")

    headers = {'Authorization': 'Basic '+Authorization}

    return headers

# sometimes milliseconds isn't reported in FMS - use this to fix that
def str2dte(timeString):
    """Converts datetime string that may contain decimal seconds

    Args:
        timeString (str): string of format %Y-%m-%dT%H:%M:%S(.%f)

    Returns:
        timeObject (datetime.datetime)

    """
    try:
        timeObject = datetime.datetime.strptime(timeString, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        timeObject = datetime.datetime.strptime(timeString, "%Y-%m-%dT%H:%M:%S")
    
    return timeObject

def getMatchesFromFMS(year:int, eventCode:str, program:str, authUsr:str=CREDENTIALS['FRC_username'], authKey:str=CREDENTIALS['FRC_key']):
    """Connects to FRC FMS records for an event and stores them

    Args:
        year (int): season year
        eventCode (str): event code
        program (str): FIRST program; 'FRC' or 'FTC'
        authUsr (str): username for respective FRC/FTC api
        authKey (str): key for respective FRC/FTC api

    Returns:
        matchesRaw (list): [{'X0': {start': datetime.datetime, 'post': datetime.datetime, 'teamsRed': list(int), 'teamsBlue': list(int)]}, ...]

    """
    # enforce program input
    if program not in ('FRC', 'FTC'):
        raise ValueError(f"Invalid input: {program}, must be 'FRC' or 'FTC'.")

    # define API url and request headers, based on: https://frc-api-docs.firstinspires.org/#733f4607-ab40-4e00-b3e1-36cfb1a2e77e
    if program == 'FRC':
        url = 'https://frc-api.firstinspires.org/v3.0/'+str(year)+'/matches/'+eventCode
    elif program == 'FTC':
        url = 'http://ftc-api.firstinspires.org/v2.0/'+str(year)+'/matches/'+eventCode
    headers = prepareHeadersFMS(authUsr, authKey)

    # make the API call (separately to prevent stale results)
    responseQuals = requests.get(url+'?tournamentLevel=Qualification', headers=headers)
    responsePlayoffs = requests.get(url+'?tournamentLevel=Playoff', headers=headers)

    # combine the two match calls together
    if program == 'FRC':
        matchesRaw = responseQuals.json()['Matches'] + responsePlayoffs.json()['Matches']
    elif program == 'FTC':
        matchesRaw = responseQuals.json()['matches'] + responsePlayoffs.json()['matches']
    
    return matchesRaw

def rewrapMatches(matchesRaw:list, program:str, timezone_str:str):
    """Reformats FMS matches response into a list of match dictionaries

    Args:
        matchesRaw (list): are the matches qualifications?
        program (str): FIRST program; 'FRC' or 'FTC'
        timezone (str): timezone of the event

    Returns:
        matchesSorted (list): [{'X0': {start': datetime.datetime, 'post': datetime.datetime, 'teamsRed': list(int), 'teamsBlue': list(int)]}, ...]
    
    """
    timezone = pytz.timezone(timezone_str)

    # reorganize them for future work
    matchesCleaned = []
    for match in matchesRaw:
        if (match['actualStartTime'] != None)*(match['postResultTime'] != None):
            matchDict = {}
            # match ID (special things for finals)
            if program == 'FRC':
                if 'Final' in match['description']:
                    playoffsCount = len([match['matchNumber'] for match in matchesRaw if ((match['tournamentLevel']=='Playoff')and not('Final' in match['description']))])
                    matchDict['id'] = 'F'+str(match['matchNumber']-playoffsCount)
                else:
                    matchDict['id'] = match['tournamentLevel'][0]+str(match['matchNumber'])
            elif program == 'FTC':
                if match['tournamentLevel'][0] == 'P':
                    matchDict['id'] = match['tournamentLevel'][0]+str(match['series'])
                else:
                    matchDict['id'] = match['tournamentLevel'][0]+str(match['matchNumber'])
            # match information
            matchDict['start'] = timezone.localize(str2dte(match['actualStartTime']))
            matchDict['post'] = timezone.localize(str2dte(match['postResultTime']))
            matchDict['teamsRed'] = [team['teamNumber'] for team in match['teams'] if team['station'][0]=='R']
            matchDict['teamsBlue'] = [team['teamNumber'] for team in match['teams'] if team['station'][0]=='B']
            # replay tag bool
            if program == 'FRC':
                matchDict['isReplay'] = match['isReplay']
            else:
                matchDict['isReplay'] = None
            matchesCleaned.append(matchDict)

    # sort the matches by start time
    matchesSorted = sorted(matchesCleaned, key=lambda x: x["start"])

    return matchesSorted

def getEventInfoFromFMS(year:int, eventCode:str, program:str, authUsr:str=CREDENTIALS['FRC_username'], authKey:str=CREDENTIALS['FRC_key']):
    """Connects to FIRST Events API and retrieves event information

    Note: FTC and FRC have different response formats (especially for timezones)

    Args:
        year (int): season year
        eventCode (str): event code
        program (str): FIRST program; 'FRC' or 'FTC'
        authUsr (str): username for respective FRC/FTC api
        authKey (str): key for respective FRC/FTC api

    Returns:
        eventInfo (dict): {'code': 'INLaf', 'name': 'Boiler Bot Battle', 'timezone': 'Eastern Standard Time', ...}

    """
    # enforce program input
    if program not in ('FRC', 'FTC'):
        raise ValueError(f"Invalid input: {program}, must be 'FRC' or 'FTC'.")

    # define API url and request headers, based on: https://frc-api-docs.firstinspires.org/#733f4607-ab40-4e00-b3e1-36cfb1a2e77e
    if program == 'FRC':
        url = 'https://frc-api.firstinspires.org/v3.0/'+str(year)+'/events?eventCode='+eventCode
    elif program == 'FTC':
        url = 'http://ftc-api.firstinspires.org/v2.0/'+str(year)+'/events?eventCode='+eventCode
    headers = prepareHeadersFMS(authUsr, authKey)

    # make the API call (separately to prevent stale results)
    response = requests.get(url, headers=headers).json()

    # extract event information from response (dear FIRST: Why is the capitalization of 'events' different?)
    if program == 'FRC':
        eventInfo = response['Events'][0]
    elif program == 'FTC':
        eventInfo = response['events'][0]
    
    return eventInfo

def livestreamDescription(matches:list, originMin:int, originSec:int,  originMatchID:str = 'Q1'):
    """Generates a string that can be placed in the description of a YouTube livestream recording to provide timestamps for matches

    Args:
        matches (list): list of match info dictionaries
        originMin (int): start time of origin match (minutes part)
        originSec (int): start time of origin match (seconds part)
        originMatchID (str): origin match string identifier

    Returns:
        str : youtube session
    """
    # prepare output string with header
    desc = '== Matches ==\n'

    # convert origin input time (subtract 3 for MC countdown)
    origin = datetime.timedelta(minutes=originMin, seconds=originSec-3)

    # verify user input is real match
    try:
        originStart = [match for match in matches if match["id"] == originMatchID][0]['start']
    except IndexError:
        raise KeyError('match ID does not exist')

    # add the match ID and match start time to output string
    for match in matches:
        desc += str(match['start'] - originStart + origin).split(".")[0] + " " + match['id'] + "\n"

    # share the results
    print(desc)
    return desc