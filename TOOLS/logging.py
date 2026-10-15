def match2str(match:dict, event_code:str):
    """
    Formats a file-name-safe string that is unique for a match

    Args:
        match (dict): {'id': X00, 'start':datetime.datetime, 'post':...}
        event_code (str): FMS event code
    
    Returns:
        str

    """
    return f"{event_code}_{match['id']}_{match['start'].hour:02}{match['start'].minute:02}"


def listNotInLog(logPath:str, matches:list, event_code:str):
    """
    Return matches where their related match2str was not found in log file

    Args:
        logPath (str): path and name of log file
        matches (list): contains match data dictionaries
        event_code (str): FMS event code
    
    Returns:
        list: matches not found in log file

    """

    # Open the file and save lines to list
    with open(logPath, 'r') as file:
        lines_list = [line.strip() for line in file]
    
    # Return matches that do not appear
    return [match for match in matches if not(match2str(match, event_code) in lines_list)]