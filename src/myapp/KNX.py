import datetime
import math
import threading
import sys
from pathlib import Path

import pytz
import struct, math

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from myapp import SectorRunner, configuration, sun  # type: ignore
else:
    from . import SectorRunner, configuration, sun  # type: ignore

def decode_dpt9(byte_pair):
    hi, lo = byte_pair            # hi = erstes Byte (MEEEEMMM), lo = zweites Byte (MMMMMMMM)
    value = (hi << 8) | lo        # 16-bit zusammenbauen
    if value == 0x7FFF: # Sentinel für "invalid"
        return math.nan
    E = (value >> 11) & 0xF # Exponent (Bits 14..11)
    m_raw = ((value & 0x8000) >> 4) | (value & 0x0700) | (value & 0x00FF) # Mantisse (12 Bit, Zweierkomplement): Bit15 + Bits10..8 + Bits7..0
    M = m_raw - 0x1000 if (m_raw & 0x800) else m_raw # Zweierkomplement auf vorzeichenbehaftet wandeln (12 Bit)
    return 0.01 * M * (1 << E)

def decode_dpt8(byte_pair):
    hi, lo = byte_pair            # hi = erstes Byte (MEEEEMMM), lo = zweites Byte (MMMMMMMM)
    value = (hi << 8) | lo        # 16-bit zusammenbauen
    if value > 32767:
        value -= 65536
    return value

def decode_dpt14(byte_quad):
    b = bytes(byte_quad)
    if len(b) != 4:
        raise ValueError("DPT14 requires exactly 4 bytes") 
    uint = struct.unpack('!I', b)[0] # KNX uses big-endian (network) byte order; interpret as IEEE 754 single-precision
    if uint == 0x7FFFFFFF:  # KNX "invalid" sentinel
        return math.nan
    return struct.unpack('!f', b)[0]

def telegram_received(telegram):
    try:
        """Callback for received KNX telegrams."""
        if configuration.Debug: print(f"Received KNX telegram: {telegram}")

        if configuration.az_el_option == "BusTime":
            if str(telegram.destination_address) == configuration.time_address:
                try:
                    hour = telegram.payload.value.value[0] & 0b00011111
                    minute = telegram.payload.value.value[1] & 0b00111111
                    second = telegram.payload.value.value[2] & 0b00111111
                except Exception as e:
                    print(f"Error decoding time from bus: {e}")
                    return
                print(f"Time from bus: {hour}:{minute}:{second}")
                current_year = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).year
                current_month = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).month
                current_day = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).day
                internal_year = (datetime.datetime.now(pytz.timezone(sun.tz))).year
                internal_month = (datetime.datetime.now(pytz.timezone(sun.tz))).month
                internal_day = (datetime.datetime.now(pytz.timezone(sun.tz))).day
                internal_hour = (datetime.datetime.now(pytz.timezone(sun.tz))).hour
                internal_minute = (datetime.datetime.now(pytz.timezone(sun.tz))).minute
                internal_second = (datetime.datetime.now(pytz.timezone(sun.tz))).second
                sun.timedelta = datetime.datetime(internal_year,internal_month,internal_day,internal_hour,internal_minute,internal_second) - datetime.datetime(current_year,current_month,current_day,hour,minute,second)
                print(f"Time difference: {sun.timedelta}")
                sun.calculate_solar_position()

            if str(telegram.destination_address) == configuration.date_address:
                try:
                    day = telegram.payload.value.value[0] & 0b00011111
                    month = telegram.payload.value.value[1] & 0b00001111
                    raw_year = telegram.payload.value.value[2] & 0b01111111
                except Exception as e:
                    print(f"Error decoding date from bus: {e}")
                    return
                if raw_year >= 90:
                    year = 1900 + raw_year
                else:
                    year = 2000 + raw_year
                print(f"Date from bus: {year}-{month}-{day}")
                current_hour = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).hour
                current_minute = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).minute
                current_second = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta).second
                internal_year = (datetime.datetime.now(pytz.timezone(sun.tz))).year
                internal_month = (datetime.datetime.now(pytz.timezone(sun.tz))).month
                internal_day = (datetime.datetime.now(pytz.timezone(sun.tz))).day
                internal_hour = (datetime.datetime.now(pytz.timezone(sun.tz))).hour
                internal_minute = (datetime.datetime.now(pytz.timezone(sun.tz))).minute
                internal_second = (datetime.datetime.now(pytz.timezone(sun.tz))).second
                sun.timedelta = datetime.datetime(internal_year,internal_month,internal_day,internal_hour,internal_minute,internal_second) - datetime.datetime(year,month,day,current_hour,current_minute,current_second)
                print(f"Time difference: {sun.timedelta}")

        if configuration.az_el_option == "BusAzEl":
            if str(telegram.destination_address) == configuration.azimuth_address:
                try:
                    if configuration.azimuth_dpt == 5.003:
                        azimuth = telegram.payload.value.value[0] / 255 * 360
                    elif configuration.azimuth_dpt == 8.011:
                        azimuth = decode_dpt8(telegram.payload.value.value)
                    elif configuration.azimuth_dpt == 14.007:
                        azimuth = decode_dpt14(telegram.payload.value.value)
                except Exception as e:
                    print(f"Error decoding azimuth from bus: {e}")
                    return
                print(f"Azimuth from bus: {azimuth}°")
                sun.current_azimuth = azimuth

            if str(telegram.destination_address) == configuration.elevation_address:
                try:
                    if configuration.elevation_dpt == 5.003:
                        elevation = telegram.payload.value.value[0] / 255 * 360
                    elif configuration.elevation_dpt == 8.011:
                        elevation = decode_dpt8(telegram.payload.value.value)
                    elif configuration.elevation_dpt == 14.007:
                        elevation = decode_dpt14(telegram.payload.value.value)
                except Exception as e:
                    print(f"Error decoding elevation from bus: {e}")
                    return
                print(f"Elevation from bus: {elevation}°")
                sun.current_elevation = elevation

        for sector in configuration.sectors:
            if str(telegram.destination_address) == sector["BrightnessAddress"] and sector["UseBrightness"]:
                try:
                    val = decode_dpt9(telegram.payload.value.value)
                except Exception as e:
                    print(f"Error decoding telegram payload: {e}")
                    return
                print(f"Brightness from bus for {sector['Name']}: {val} Lux")
                with SectorRunner.sectors_lock:
                    sector_state = SectorRunner.sectors[sector["GUID"]]
                    sector_state["Brightness"] = val
                    if val > sector["BrightnessUpperThreshold"] and sector_state.get("brightness_state", 1) == 1:
                        sector_state["brightness_state"] = 3
                        sector_state["brightness_timer_on"] = threading.Timer(sector["BrightnessUpperDelay"], SectorRunner.set_brightness_state, args=(sector["GUID"], 4))
                        sector_state["brightness_timer_on"].daemon = True
                        sector_state["brightness_timer_on"].start()
                    elif val > sector["BrightnessUpperThreshold"] and sector_state.get("brightness_state", 1) == 2:
                        sector_state["brightness_state"] = 4
                        sector_state["brightness_timer_off"].cancel()
                    elif val < sector["BrightnessLowerThreshold"] and sector_state.get("brightness_state", 1) == 3:
                        sector_state["brightness_state"] = 1
                        sector_state["brightness_timer_on"].cancel()
                    elif val < sector["BrightnessLowerThreshold"] and sector_state.get("brightness_state", 1) == 4:
                        sector_state["brightness_state"] = 2
                        sector_state["brightness_timer_off"] = threading.Timer(sector["BrightnessLowerDelay"], SectorRunner.set_brightness_state, args=(sector["GUID"], 1))
                        sector_state["brightness_timer_off"].daemon = True
                        sector_state["brightness_timer_off"].start()

            if str(telegram.destination_address) == sector["IrradianceAddress"] and sector["UseIrradiance"]:
                try:
                    val = decode_dpt9(telegram.payload.value.value)
                except Exception as e:
                    print(f"Error decoding telegram payload: {e}")
                    return
                print(f"Irradiance from bus for {sector['Name']}: {val} Lux")
                with SectorRunner.sectors_lock:
                    sector_state = SectorRunner.sectors[sector["GUID"]]
                    sector_state["Irradiance"] = val
                    if val > sector["IrradianceUpperThreshold"] and sector_state.get("irradiance_state", 1) == 1:
                        sector_state["irradiance_state"] = 3
                        sector_state["irradiance_timer_on"] = threading.Timer(sector["IrradianceUpperDelay"], SectorRunner.set_irradiance_state, args=(sector["GUID"], 4))
                        sector_state["irradiance_timer_on"].daemon = True
                        sector_state["irradiance_timer_on"].start()
                    elif val > sector["IrradianceUpperThreshold"] and sector_state.get("irradiance_state", 1) == 2:
                        sector_state["irradiance_state"] = 4
                        sector_state["irradiance_timer_off"].cancel()
                    elif val < sector["IrradianceLowerThreshold"] and sector_state.get("irradiance_state", 1) == 3:
                        sector_state["irradiance_state"] = 1
                        sector_state["irradiance_timer_on"].cancel()
                    elif val < sector["IrradianceLowerThreshold"] and sector_state.get("irradiance_state", 1) == 4:
                        sector_state["irradiance_state"] = 2
                        sector_state["irradiance_timer_off"] = threading.Timer(sector["IrradianceLowerDelay"], SectorRunner.set_irradiance_state, args=(sector["GUID"], 1))
                        sector_state["irradiance_timer_off"].daemon = True
                        sector_state["irradiance_timer_off"].start()
            
            if str(telegram.destination_address) == sector["OnAutoAddress"]:
                try:
                    val = telegram.payload.value.value
                except Exception as e:
                    print(f"Error decoding telegram payload: {e}")
                    return
                if sector["OnAutoBehavior"] == "Auto":
                    mode = val
                else:
                    mode = not val
                if configuration.Debug: print(f"Sector {sector['Name']} set to {'Auto' if mode else 'On'} mode from bus")
                with SectorRunner.sectors_lock:
                    SectorRunner.sectors[sector["GUID"]]["Mode"] = "Auto" if mode else "On"

            if str(telegram.destination_address) == sector["OffAutoAddress"]:
                try:
                    val = telegram.payload.value.value == 1
                except Exception as e:
                    print(f"Error decoding telegram payload: {e}")
                    return
                if sector["OffAutoBehavior"] == "Auto":
                    mode = val
                else:
                    mode = not val
                if configuration.Debug: print(f"Sector {sector['Name']} set to {'Auto' if mode else 'Off'} mode from bus")
                with SectorRunner.sectors_lock:
                    SectorRunner.sectors[sector["GUID"]]["Mode"] = "Auto" if mode else "Off"
    except Exception as e:
        print(f"Error processing telegram: {e}")
