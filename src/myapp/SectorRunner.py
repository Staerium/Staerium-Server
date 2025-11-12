from xknx.devices import NumericValue, Switch
import asyncio
import math

from . import configuration, sun
import threading

xknx = None

loop_count = 10000
lps = 0

sectors = {}

for sector in configuration.sectors:
    sectors[sector["GUID"]] = {}
    sectors[sector["GUID"]]["Mode"] = "Auto"

def calculate_lps():
    threading.Timer(10.0, calculate_lps).start()
    global lps 
    global loop_count
    lps = loop_count / 10
    if lps < 1:
        print(f"Server is running really slow! Please check your configuration and hardware. (LPS = {lps})")
    else:
        if configuration.Debug: print(f"LPS: {lps}")
    loop_count = 0


def set_brightness_state(guid, state):
    sectors[guid]["brightness_state"] = state
    if configuration.Debug: print(f"Sector {guid} brightness state set to {state}")

def set_irradiance_state(guid, state):
    sectors[guid]["irradiance_state"] = state
    if configuration.Debug: print(f"Sector {guid} irradiance state set to {state}")



def start(loop):
    global sun
    global loop_count
    calculate_lps()
    for sector in configuration.sectors:
        if sector["HeightAddress"] != "":
            sectors[sector["GUID"]]["HeightSender"] = NumericValue(xknx=xknx, name=f"{sector["GUID"]}_height", group_address=sector["HeightAddress"], respond_to_read=True, value_type=5)
        else:
            sectors[sector["GUID"]]["HeightSender"] = NumericValue(xknx=xknx, name=f"{sector["GUID"]}_height", group_address=None, respond_to_read=True, value_type=5)
        xknx.devices.async_add(sectors[sector["GUID"]]["HeightSender"])

        if sector["LouvreAngleAddress"] != "":
            sectors[sector["GUID"]]["LouvreAngleSender"] = NumericValue(xknx=xknx, name=f"{sector["GUID"]}_louvre_angle", group_address=sector["LouvreAngleAddress"], respond_to_read=True, value_type=5)
        else:
            sectors[sector["GUID"]]["LouvreAngleSender"] = NumericValue(xknx=xknx, name=f"{sector["GUID"]}_louvre_angle", group_address=None, respond_to_read=True, value_type=5)
        xknx.devices.async_add(sectors[sector["GUID"]]["LouvreAngleSender"])

        if sector["SunBoolAddress"] != "":
            sectors[sector["GUID"]]["SunBoolSender"] = Switch(xknx=xknx, name=f"{sector["GUID"]}_sun_bool", group_address=sector["SunBoolAddress"], respond_to_read=True)
        else:
            print(f"Warning: Sector {sector['GUID']} has no SunBoolAddress defined. Sun state will not be sent to KNX for this sector.")
            sectors[sector["GUID"]]["SunBoolSender"] = Switch(xknx=xknx, name=f"{sector["GUID"]}_sun_bool", group_address=None, respond_to_read=True)
        xknx.devices.async_add(sectors[sector["GUID"]]["SunBoolSender"])


    while True:
        loop_count = loop_count + 1
        if configuration.az_el_option != "BusAzEl":
            sun.calculate_solar_position()
        for sector in configuration.sectors:
            relative_azimuth = (sun.current_azimuth - sector["Orientation"])
            if relative_azimuth > 180:
                relative_azimuth = relative_azimuth - 360
            if sector["UseBrightness"]:
                if sector["UseIrradiance"]:
                    if sector["BrightnessIrradianceLink"] == "And":
                        sun_state = (sectors[sector["GUID"]].get("brightness_state", 1) == 4 and sectors[sector["GUID"]].get("irradiance_state", 1) == 4 and sectors[sector["GUID"]].get("Mode") == "Auto") or (sectors[sector["GUID"]].get("Mode") == "On")
                    else:
                        sun_state = ((sectors[sector["GUID"]].get("brightness_state", 1) == 4 or sectors[sector["GUID"]].get("irradiance_state", 1) == 4) and sectors[sector["GUID"]].get("Mode") == "Auto") or (sectors[sector["GUID"]].get("Mode") == "On")
                else:
                    sun_state = (sectors[sector["GUID"]].get("brightness_state", 1) == 4 and sectors[sector["GUID"]].get("Mode") == "Auto") or (sectors[sector["GUID"]].get("Mode") == "On")
            else:
                sun_state = (sectors[sector["GUID"]].get("irradiance_state", 1) == 4 and sectors[sector["GUID"]].get("Mode") == "Auto") or (sectors[sector["GUID"]].get("Mode") == "On")
            
            # Sun shines on facade check
            if sun_state and (not (relative_azimuth >= -90 and relative_azimuth <= 90)) and sun.current_elevation >= 0:
                sun_state = False
            
            # Horizon limit check
            if sun_state and sector["HorizonLimit"]:
                if horizon_limit_check(sector, relative_azimuth, sun.current_elevation) == False:
                    sun_state = False

            #Send KNX updates if state changed
            if sun_state != sectors[sector["GUID"]].get("sun_state", None):
                sectors[sector["GUID"]]["sun_state"] = sun_state
                print(f"Sector {sector['GUID']} sun state changed to {'On' if sun_state else 'Off'}")
                if sun_state:
                    future = asyncio.run_coroutine_threadsafe(sectors[sector["GUID"]]["SunBoolSender"].set_on(), loop)
                    future.result()
                    future = asyncio.run_coroutine_threadsafe(sectors[sector["GUID"]]["HeightSender"].set(255), loop)
                    future.result()
                else:
                    future = asyncio.run_coroutine_threadsafe(sectors[sector["GUID"]]["SunBoolSender"].set_off(), loop)
                    future.result()

            # Louvre tracking
            elif sector["LouvreTracking"] and sun_state:
                angle_deg = louvre_angle_calculation(sector["LouvreSpacing"], sector["LouvreDepth"], relative_azimuth, sun.current_elevation)
                # Map calculated angle (degrees) to 0-100% between sector-defined zero and hundred angles,
                # then convert that percent to the device value (0-255) expected by NumericValue (value_type=5).
                zero_deg = sector.get("LouvreAngleAtZero", 0.0)
                hundred_deg = sector.get("LouvreAngleAtHundred", 90.0)
                span = hundred_deg - zero_deg
                if span == 0:
                    angle_percent = 100.0 if angle_deg >= hundred_deg else 0.0
                else:
                    angle_percent = (angle_deg - zero_deg) / span * 100.0


                if sectors[sector["GUID"]].get("angle_deg", 0) < angle_deg:
                    sectors[sector["GUID"]]["angle_direction"] = "opening"
                elif sectors[sector["GUID"]].get("angle_deg", 0) > angle_deg:
                    sectors[sector["GUID"]]["angle_direction"] = "closing"
                sectors[sector["GUID"]]["angle_deg"] = angle_deg
                
                if sectors[sector["GUID"]].get("angle_direction", "closing") == "opening":
                    angle_percent = angle_percent + sector.get("LouvreBuffer", 0)
                else:
                    angle_percent = angle_percent + sector.get("LouvreBuffer", 0) + sector.get("LouvreMinimumChange", 1)

                # clamp 0..100
                angle_percent = max(0.0, min(100.0, angle_percent))
                # convert percent (0-100) to 0-255 for the NumericValue device
                angle_bytes = int(round(angle_percent * 255.0 / 100.0))

                if abs(sectors[sector["GUID"]].get("angle_bytes_sent", 180) - angle_bytes) >= sector.get("LouvreMinimumChange", 1):    
                    sectors[sector["GUID"]]["angle_bytes_sent"] = angle_bytes
                    future = asyncio.run_coroutine_threadsafe(sectors[sector["GUID"]]["LouvreAngleSender"].set(angle_bytes), loop)
                    future.result()
                    print(f"Sector {sector['GUID']} louvre angle deg={angle_deg:.2f} => {angle_percent:.1f}% => bytes={angle_bytes}")


def horizon_limit_check(sector, relative_azimuth, current_elevation):
    def _interpolate(points, target_x, is_ceiling=False):
        if not points:
            return None

        sorted_points = sorted(points, key=lambda point: point.get("X", 0))

        if target_x <= sorted_points[0].get("X", 0):
            return sorted_points[0].get("Y")

        if target_x >= sorted_points[-1].get("X", 0):
            return sorted_points[-1].get("Y")

        for lower, upper in zip(sorted_points, sorted_points[1:]):
            lower_x = lower.get("X", 0)
            upper_x = upper.get("X", 0)

            if lower_x <= target_x <= upper_x:
                lower_y = lower.get("Y")
                upper_y = upper.get("Y")

                if upper_x == lower_x:
                    if is_ceiling:
                        if upper_y < lower_y:
                            return lower_y
                        else:
                            return upper_y
                    else:
                        if upper_y < lower_y:
                            return upper_y
                        else:
                            return lower_y

                fraction = (target_x - lower_x) / (upper_x - lower_x)
                return lower_y + fraction * (upper_y - lower_y)

        return None

    horizon_value = _interpolate(sector.get("HorizonPoints", []), relative_azimuth, is_ceiling=False)
    ceiling_value = _interpolate(sector.get("CeilingPoints", []), relative_azimuth, is_ceiling=True)

    if horizon_value is not None and current_elevation < horizon_value:
        return False

    if ceiling_value is not None and current_elevation > ceiling_value:
        return False

    return True


def louvre_angle_calculation(louvre_spacing, louvre_depth, relative_azimuth, current_elevation):
    current_elevation_rad = math.radians(current_elevation)
    relative_azimuth_rad = math.radians(relative_azimuth)
    tany = math.tan(current_elevation_rad)/math.cos(relative_azimuth_rad)
    for i in range(511, 0, -1):
        louvre_angle_rad = math.radians(i * 90 / 511)
        if tany > (louvre_spacing - math.cos(louvre_angle_rad) * louvre_depth) / (math.sin(louvre_angle_rad) * louvre_depth):
            return i * 90 / 511
    return 90
