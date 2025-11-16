import datetime
import sys
from pathlib import Path

import pytz
from pandas import DatetimeIndex
from pvlib import solarposition
from pvlib.location import Location

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from myapp import configuration  # type: ignore
else:
    from . import configuration  # type: ignore


tz = configuration.az_el_timezone

site = Location(configuration.latitude, configuration.longitude, tz=tz)

current_azimuth = 0.0
current_elevation = -90.0

timedelta = datetime.timedelta(0)


def calculate_solar_position():
    """Calculate the solar position (azimuth and elevation) based on the current time and location."""
    global current_azimuth
    global current_elevation
    global tz
    global site
    if configuration.az_el_option == "Internet":
        times = DatetimeIndex([datetime.datetime.now(pytz.timezone(tz))], tz=tz)
    elif configuration.az_el_option == "BusTime":
        times = DatetimeIndex([datetime.datetime.now(pytz.timezone(tz)) - timedelta], tz=tz) # Adjust for time difference from bus
    else:
        return  # Do not calculate if using BusAzEl
    solpos = site.get_solarposition(times)
    current_azimuth = solpos['azimuth'].values[0]
    current_elevation = solpos['elevation'].values[0]


#TODO: Everything
