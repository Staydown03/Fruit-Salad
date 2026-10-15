import requests
import datetime
import pytz

url = "https://raw.githubusercontent.com/unicode-org/cldr/main/common/supplemental/windowsZones.xml"
response = requests.get(url)
xml_content = response.text

import xml.etree.ElementTree as ET

# Parse the XML content
root = ET.fromstring(xml_content)

# Build the mapping dictionary
windows_to_iana = {}
for mapZone in root.findall(".//mapZone"):
    windows_name = mapZone.attrib['other']
    territory = mapZone.attrib['territory']
    iana_name = mapZone.attrib['type']
    
    # Use territory '001' for global default
    if territory == '001':
        windows_to_iana[windows_name] = iana_name

def convert_windows_to_iana(windows_tz):
    """Converts a Windows timezone to an IANA timezone.

    Args:
        windows_tz (str): The Windows timezone name.

    Returns:
        str: The corresponding IANA timezone name, or None if not found.
    """
    return windows_to_iana.get(windows_tz, None)

def convert_iana_to_str(iana_tz):
    """Converts an IANA timezone to a UTC offset string.

    Args:
        iana_tz (str): The IANA timezone name.

    Returns:
        str: The UTC offset in the format 'UTC(+/-)HH:MM'.
    """
    tz = pytz.timezone(iana_tz)
    now = datetime.datetime.now()
    localized = tz.localize(now)
    offset = localized.utcoffset()

    # Format as UTC(+/-)HH:MM
    total_minutes = int(offset.total_seconds() // 60)
    sign = '+' if total_minutes >= 0 else '-'
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"

import pytz

def offset_to_timezone(offset_str):
    """Converts a UTC offset string to a pytz timezone.

    Args:
        offset_str (str): The UTC offset string in the format 'UTC±HH:MM'.

    Returns:
        pytz.timezone: The corresponding pytz timezone object.

    Raises:
        ValueError: If the offset string format is invalid or no matching timezone is found.
    """
    # Validate format: "UTC±HH:MM"
    if not offset_str.startswith("UTC") or len(offset_str) != 9:
        raise ValueError("Invalid format. Use 'UTC±HH:MM'")

    sign = offset_str[3]
    hours = int(offset_str[4:6])
    minutes = int(offset_str[7:9])

    # Convert to total offset in hours
    total_offset = hours + minutes / 60
    if sign == '-':
        total_offset = -total_offset

    # pytz uses reversed sign in Etc/GMT zones
    gmt_offset = -int(total_offset)
    tz_name = f"Etc/GMT{gmt_offset:+d}"

    if tz_name in pytz.all_timezones:
        return pytz.timezone(tz_name)
    else:
        raise ValueError(f"No matching timezone for offset {offset_str}")