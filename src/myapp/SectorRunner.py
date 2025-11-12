from xknx.devices import NumericValue, Switch
import asyncio
import math
import time

from . import configuration, sun
import threading

xknx = None

loop_count = 10000
lps = 0

sectors = {}
sectors_lock = threading.Lock()

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
    with sectors_lock:
        sectors[guid]["brightness_state"] = state
    if configuration.Debug: print(f"Sector {guid} brightness state set to {state}")

def set_irradiance_state(guid, state):
    with sectors_lock:
        sectors[guid]["irradiance_state"] = state
    if configuration.Debug: print(f"Sector {guid} irradiance state set to {state}")



def start(loop):
    global sun
    global loop_count
    calculate_lps()
    for sector in configuration.sectors:
        guid = sector["GUID"]

        if sector["HeightAddress"] != "":
            height_sender = NumericValue(xknx=xknx, name=f"{guid}_height", group_address=sector["HeightAddress"], respond_to_read=True, value_type=5)
        else:
            height_sender = NumericValue(xknx=xknx, name=f"{guid}_height", group_address=None, respond_to_read=True, value_type=5)
        xknx.devices.async_add(height_sender)
        with sectors_lock:
            sectors[guid]["HeightSender"] = height_sender

        if sector["LouvreAngleAddress"] != "":
            louvre_sender = NumericValue(xknx=xknx, name=f"{guid}_louvre_angle", group_address=sector["LouvreAngleAddress"], respond_to_read=True, value_type=5)
        else:
            louvre_sender = NumericValue(xknx=xknx, name=f"{guid}_louvre_angle", group_address=None, respond_to_read=True, value_type=5)
        xknx.devices.async_add(louvre_sender)
        with sectors_lock:
            sectors[guid]["LouvreAngleSender"] = louvre_sender

        if sector["SunBoolAddress"] != "":
            sun_bool_sender = Switch(xknx=xknx, name=f"{guid}_sun_bool", group_address=sector["SunBoolAddress"], respond_to_read=True)
        else:
            print(f"Warning: Sector {sector['GUID']} has no SunBoolAddress defined. Sun state will not be sent to KNX for this sector.")
            sun_bool_sender = Switch(xknx=xknx, name=f"{guid}_sun_bool", group_address=None, respond_to_read=True)
        xknx.devices.async_add(sun_bool_sender)
        with sectors_lock:
            sectors[guid]["SunBoolSender"] = sun_bool_sender


    while True:
        loop_count = loop_count + 1
        if configuration.az_el_option != "BusAzEl":
            sun.calculate_solar_position()
        for sector in configuration.sectors:
            guid = sector["GUID"]
            with sectors_lock:
                sector_state = sectors[guid]
                brightness_state = sector_state.get("brightness_state", 1)
                irradiance_state = sector_state.get("irradiance_state", 1)
                mode_state = sector_state.get("Mode")
                sun_bool_sender = sector_state.get("SunBoolSender")
                height_sender = sector_state.get("HeightSender")
                louvre_sender = sector_state.get("LouvreAngleSender")

            relative_azimuth = (sun.current_azimuth - sector["Orientation"])
            if relative_azimuth > 180:
                relative_azimuth = relative_azimuth - 360
            brightness_active = brightness_state == 4
            irradiance_active = irradiance_state == 4
            if sector["UseBrightness"]:
                if sector["UseIrradiance"]:
                    if sector["BrightnessIrradianceLink"] == "And":
                        sun_state = (brightness_active and irradiance_active and mode_state == "Auto") or (mode_state == "On")
                    else:
                        sun_state = ((brightness_active or irradiance_active) and mode_state == "Auto") or (mode_state == "On")
                else:
                    sun_state = (brightness_active and mode_state == "Auto") or (mode_state == "On")
            else:
                sun_state = (irradiance_active and mode_state == "Auto") or (mode_state == "On")
            
            # Sun shines on facade check
            if sun_state and (not (relative_azimuth >= -90 and relative_azimuth <= 90)) and sun.current_elevation >= 0:
                sun_state = False
            
            # Horizon limit check
            if sun_state and sector["HorizonLimit"]:
                if horizon_limit_check(sector, relative_azimuth, sun.current_elevation) == False:
                    sun_state = False

            #Send KNX updates if state changed
            state_changed = False
            with sectors_lock:
                current_state = sectors[guid].get("sun_state", None)
                if sun_state != current_state:
                    sectors[guid]["sun_state"] = sun_state
                    state_changed = True

            if state_changed:
                print(f"Sector {sector['GUID']} sun state changed to {'On' if sun_state else 'Off'}")
                if sun_state:
                    if sun_bool_sender:
                        future = asyncio.run_coroutine_threadsafe(sun_bool_sender.set_on(), loop)
                        future.result()
                    if height_sender:
                        future = asyncio.run_coroutine_threadsafe(height_sender.set(255), loop)
                        future.result()
                else:
                    if sun_bool_sender:
                        future = asyncio.run_coroutine_threadsafe(sun_bool_sender.set_off(), loop)
                        future.result()

            # Louvre tracking
            elif sector["LouvreTracking"] and sun_state and louvre_sender:
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

                with sectors_lock:
                    previous_angle_deg = sectors[guid].get("angle_deg", 0)
                    if previous_angle_deg < angle_deg:
                        angle_direction = "opening"
                    elif previous_angle_deg > angle_deg:
                        angle_direction = "closing"
                    else:
                        angle_direction = sectors[guid].get("angle_direction", "closing")
                    sectors[guid]["angle_direction"] = angle_direction
                    sectors[guid]["angle_deg"] = angle_deg
                
                if angle_direction == "opening":
                    angle_percent = angle_percent + sector.get("LouvreBuffer", 0)
                else:
                    angle_percent = angle_percent + sector.get("LouvreBuffer", 0) + sector.get("LouvreMinimumChange", 1)

                # clamp 0..100
                angle_percent = max(0.0, min(100.0, angle_percent))
                # convert percent (0-100) to 0-255 for the NumericValue device
                angle_bytes = int(round(angle_percent * 255.0 / 100.0))

                should_send_angle = False
                with sectors_lock:
                    last_angle_bytes = sectors[guid].get("angle_bytes_sent", 180)
                    if abs(last_angle_bytes - angle_bytes) >= sector.get("LouvreMinimumChange", 1):
                        sectors[guid]["angle_bytes_sent"] = angle_bytes
                        should_send_angle = True

                if should_send_angle:
                    future = asyncio.run_coroutine_threadsafe(louvre_sender.set(angle_bytes), loop)
                    future.result()
                    print(f"Sector {sector['GUID']} louvre angle deg={angle_deg:.2f} => {angle_percent:.1f}% => bytes={angle_bytes}")
        time.sleep(0.001)


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
