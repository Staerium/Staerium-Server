import datetime
import logging
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

logger = logging.getLogger(__name__)

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

def _get_lowest_brightness_threshold_high(sector):
    if not sector.get("BrightnessDelayHigh"):
        return sector.get("BrightnessUpperThreshold")
    return min(point.get("Brightness", float('inf')) for point in sector["BrightnessDelayHigh"]["Point"])

def _get_highest_brightness_threshold_low(sector):
    if not sector.get("BrightnessDelayLow"):
        return sector.get("BrightnessLowerThreshold")
    return max(point.get("Brightness", float(0)) for point in sector["BrightnessDelayLow"]["Point"])

def _get_lowest_irradiance_threshold_high(sector):
    if not sector.get("IrradianceDelayHigh"):
        return sector.get("IrradianceUpperThreshold")
    return min(point.get("Irradiance", float('inf')) for point in sector["IrradianceDelayHigh"]["Point"])

def _get_highest_irradiance_threshold_low(sector):
    if not sector.get("IrradianceDelayLow"):
        return sector.get("IrradianceLowerThreshold")
    return max(point.get("Irradiance", float(0)) for point in sector["IrradianceDelayLow"]["Point"])

def _get_timer_interval(sector_state, key, default):
    try: 
        timer = sector_state.get(key)
        return float(timer.interval)
    except Exception:
        return default
    
def _get_dynamic_brightness_delay_high(sector, val):
    if not sector.get("BrightnessDelayHigh"):
        return sector.get("BrightnessUpperDelay")
    points = sector["BrightnessDelayHigh"]["Point"]
    if len(points) < 2:
        return points[0].get("Seconds", sector.get("BrightnessUpperDelay"))
    
    # Find the two points to interpolate between
    sorted_points = sorted(points, key=lambda p: p.get("Brightness", float('inf')))
    
    for i in range(len(sorted_points) - 1):
        x1 = sorted_points[i].get("Brightness", float('inf'))
        x2 = sorted_points[i + 1].get("Brightness", float('inf'))
        y1 = sorted_points[i].get("Seconds", sector.get("BrightnessUpperDelay"))
        y2 = sorted_points[i + 1].get("Seconds", sector.get("BrightnessUpperDelay"))
        
        if x1 <= val <= x2:
            # Linear interpolation
            if x2 == x1:
                return y1
            return y1 + (val - x1) * (y2 - y1) / (x2 - x1)
    
    # If val is outside range, return the closest point's delay
    if val < sorted_points[0].get("Brightness", float('inf')):
        return sorted_points[0].get("Seconds", sector.get("BrightnessUpperDelay"))
    else:
        return sorted_points[-1].get("Seconds", sector.get("BrightnessUpperDelay"))
    
def _get_dynamic_brightness_delay_low(sector, val):
    if not sector.get("BrightnessDelayLow"):
        return sector.get("BrightnessLowerDelay")
    points = sector["BrightnessDelayLow"]["Point"]
    if len(points) < 2:
        return points[0].get("Seconds", sector.get("BrightnessLowerDelay"))
    
    # Find the two points to interpolate between
    sorted_points = sorted(points, key=lambda p: p.get("Brightness", float('inf')))
    
    for i in range(len(sorted_points) - 1):
        x1 = sorted_points[i].get("Brightness", float('inf'))
        x2 = sorted_points[i + 1].get("Brightness", float('inf'))
        y1 = sorted_points[i].get("Seconds", sector.get("BrightnessLowerDelay"))
        y2 = sorted_points[i + 1].get("Seconds", sector.get("BrightnessLowerDelay"))
        
        if x1 <= val <= x2:
            # Linear interpolation
            if x2 == x1:
                return y1
            return y1 + (val - x1) * (y2 - y1) / (x2 - x1)
    
    # If val is outside range, return the closest point's delay
    if val < sorted_points[0].get("Brightness", float('inf')):
        return sorted_points[0].get("Seconds", sector.get("BrightnessLowerDelay"))
    else:
        return sorted_points[-1].get("Seconds", sector.get("BrightnessLowerDelay"))

def _get_dynamic_irradiance_delay_high(sector, val):
    if not sector.get("IrradianceDelayHigh"):
        return sector.get("IrradianceUpperDelay")
    points = sector["IrradianceDelayHigh"]["Point"]
    if len(points) < 2:
        return points[0].get("Seconds", sector.get("IrradianceUpperDelay"))
    
    # Find the two points to interpolate between
    sorted_points = sorted(points, key=lambda p: p.get("Irradiance", float('inf')))
    
    for i in range(len(sorted_points) - 1):
        x1 = sorted_points[i].get("Irradiance", float('inf'))
        x2 = sorted_points[i + 1].get("Irradiance", float('inf'))
        y1 = sorted_points[i].get("Seconds", sector.get("IrradianceUpperDelay"))
        y2 = sorted_points[i + 1].get("Seconds", sector.get("IrradianceUpperDelay"))
        
        if x1 <= val <= x2:
            # Linear interpolation
            if x2 == x1:
                return y1
            return y1 + (val - x1) * (y2 - y1) / (x2 - x1)
    
    # If val is outside range, return the closest point's delay
    if val < sorted_points[0].get("Irradiance", float('inf')):
        return sorted_points[0].get("Seconds", sector.get("IrradianceUpperDelay"))
    else:
        return sorted_points[-1].get("Seconds", sector.get("IrradianceUpperDelay"))
    
def _get_dynamic_irradiance_delay_low(sector, val):
    if not sector.get("IrradianceDelayLow"):
        return sector.get("IrradianceLowerDelay")
    points = sector["IrradianceDelayLow"]["Point"]
    if len(points) < 2:
        return points[0].get("Seconds", sector.get("IrradianceLowerDelay"))
    
    # Find the two points to interpolate between
    sorted_points = sorted(points, key=lambda p: p.get("Irradiance", float('inf')))
    
    for i in range(len(sorted_points) - 1):
        x1 = sorted_points[i].get("Irradiance", float('inf'))
        x2 = sorted_points[i + 1].get("Irradiance", float('inf'))
        y1 = sorted_points[i].get("Seconds", sector.get("IrradianceLowerDelay"))
        y2 = sorted_points[i + 1].get("Seconds", sector.get("IrradianceLowerDelay"))
        
        if x1 <= val <= x2:
            # Linear interpolation
            if x2 == x1:
                return y1
            return y1 + (val - x1) * (y2 - y1) / (x2 - x1)
    
    # If val is outside range, return the closest point's delay
    if val < sorted_points[0].get("Irradiance", float('inf')):
        return sorted_points[0].get("Seconds", sector.get("IrradianceLowerDelay"))
    else:
        return sorted_points[-1].get("Seconds", sector.get("IrradianceLowerDelay"))


def telegram_received(telegram):
    try:
        """Callback for received KNX telegrams."""
        logger.debug("Received KNX telegram: %s", telegram)

        if configuration.az_el_option == "BusTime":
            if str(telegram.destination_address) == configuration.time_address:
                try:
                    hour = telegram.payload.value.value[0] & 0b00011111
                    minute = telegram.payload.value.value[1] & 0b00111111
                    second = telegram.payload.value.value[2] & 0b00111111
                except Exception as e:
                    logger.warning("Error decoding time from bus: %s", e)
                    return
                logger.info("Time from bus: %02d:%02d:%02d", hour, minute, second)
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
                logger.info("Time difference: %s", sun.timedelta)
                sun.calculate_solar_position()

            if str(telegram.destination_address) == configuration.date_address:
                try:
                    day = telegram.payload.value.value[0] & 0b00011111
                    month = telegram.payload.value.value[1] & 0b00001111
                    raw_year = telegram.payload.value.value[2] & 0b01111111
                except Exception as e:
                    logger.warning("Error decoding date from bus: %s", e)
                    return
                if raw_year >= 90:
                    year = 1900 + raw_year
                else:
                    year = 2000 + raw_year
                logger.info("Date from bus: %04d-%02d-%02d", year, month, day)
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
                logger.info("Time difference: %s", sun.timedelta)
                logger.info("Current time: %s", datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta)

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
                    logger.warning("Error decoding azimuth from bus: %s", e)
                    return
                logger.info("Azimuth from bus: %s°", azimuth)
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
                    logger.warning("Error decoding elevation from bus: %s", e)
                    return
                logger.info("Elevation from bus: %s°", elevation)
                sun.current_elevation = elevation

        # Brightness Threshold
        for sector in configuration.sectors:
            if str(telegram.destination_address) == sector["BrightnessAddress"] and sector["UseBrightness"]:
                try:
                    val = decode_dpt9(telegram.payload.value.value)
                except Exception as e:
                    logger.warning("Error decoding telegram payload: %s", e)
                    return
                logger.info("Brightness from bus for %s: %s Lux", sector["Name"], val)
                # brightness / irradiance_state values: 
                # 1 = Below lower threshold
                # 2 = Below lower threshold, about to turn to 1 (on)
                # 3 = Above upper threshold, about to turn to 4 (off)
                # 4 = Above upper threshold
                with SectorRunner.sectors_lock:
                    sector_state = SectorRunner.sectors[sector["GUID"]]
                    sector_state["Brightness"] = val
                    if sector["BrightnessDynamicDelay"]:
                        if val > _get_lowest_brightness_threshold_high(sector):
                            if sector_state.get("brightness_state", 1) == 1:
                                sector_state["brightness_state"] = 3
                                sector_state["brightness_timer_on"] = threading.Timer(_get_dynamic_brightness_delay_high(sector, val), SectorRunner.set_brightness_state, args=(sector["GUID"], 4))
                                sector_state["brightness_timer_on"].daemon = True
                                sector_state["brightness_timer_on"].start()
                                sector_state["brightness_timer_on_start"] = datetime.datetime.now()
                            elif sector_state.get("brightness_state", 1) == 2:
                                sector_state["brightness_state"] = 4
                                sector_state["brightness_timer_off"].cancel()
                            elif sector_state.get("brightness_state", 1) == 3:
                                remaining = _get_timer_interval(sector_state, "brightness_timer_on", float('inf')) - (datetime.datetime.now() - sector_state.get("brightness_timer_on_start", datetime.datetime.now())).total_seconds()
                                if remaining > _get_dynamic_brightness_delay_high(sector, val):
                                    sector_state["brightness_timer_on"].cancel()
                                    sector_state["brightness_timer_on"] = threading.Timer(_get_dynamic_brightness_delay_high(sector, val), SectorRunner.set_brightness_state, args=(sector["GUID"], 4))
                                    sector_state["brightness_timer_on"].daemon = True
                                    sector_state["brightness_timer_on"].start()
                                    sector_state["brightness_timer_on_start"] = datetime.datetime.now()
                            elif sector_state.get("brightness_state", 1) == 4:
                                # Do Nothing, already in upper state
                                pass
                        elif val < _get_highest_brightness_threshold_low(sector):
                            if sector_state.get("brightness_state", 1) == 1:
                                # Do Nothing, already in lower state
                                pass
                            elif sector_state.get("brightness_state", 1) == 2:
                                remaining = _get_timer_interval(sector_state, "brightness_timer_off", float('inf')) - (datetime.datetime.now() - sector_state.get("brightness_timer_off_start", datetime.datetime.now())).total_seconds()
                                if remaining > _get_dynamic_brightness_delay_low(sector, val):
                                    sector_state["brightness_timer_off"].cancel()
                                    sector_state["brightness_timer_off"] = threading.Timer(_get_dynamic_brightness_delay_low(sector, val), SectorRunner.set_brightness_state, args=(sector["GUID"], 1))
                                    sector_state["brightness_timer_off"].daemon = True
                                    sector_state["brightness_timer_off"].start()
                                    sector_state["brightness_timer_off_start"] = datetime.datetime.now()
                            elif sector_state.get("brightness_state", 1) == 3:
                                sector_state["brightness_state"] = 1
                                sector_state["brightness_timer_on"].cancel()
                            elif sector_state.get("brightness_state", 1) == 4:
                                sector_state["brightness_state"] = 2
                                sector_state["brightness_timer_off"] = threading.Timer(_get_dynamic_brightness_delay_low(sector, val), SectorRunner.set_brightness_state, args=(sector["GUID"], 1))
                                sector_state["brightness_timer_off"].daemon = True
                                sector_state["brightness_timer_off"].start()
                                sector_state["brightness_timer_off_start"] = datetime.datetime.now()

                    else:
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

            # Irradiance Threshold
            if str(telegram.destination_address) == sector["IrradianceAddress"] and sector["UseIrradiance"]:
                try:
                    val = decode_dpt9(telegram.payload.value.value)
                except Exception as e:
                    logger.warning("Error decoding telegram payload: %s", e)
                    return
                logger.info("Irradiance from bus for %s: %s Lux", sector["Name"], val)
                # brightness / irradiance_state values: 
                # 1 = Below lower threshold
                # 2 = Below lower threshold, about to turn to 1 (on)
                # 3 = Above upper threshold, about to turn to 4 (off)
                # 4 = Above upper threshold
                with SectorRunner.sectors_lock:
                    sector_state = SectorRunner.sectors[sector["GUID"]]
                    sector_state["Irradiance"] = val
                    if sector["IrradianceDynamicDelay"]:
                        if val > _get_lowest_irradiance_threshold_high(sector):
                            if sector_state.get("irradiance_state", 1) == 1:
                                sector_state["irradiance_state"] = 3
                                sector_state["irradiance_timer_on"] = threading.Timer(_get_dynamic_irradiance_delay_high(sector, val), SectorRunner.set_irradiance_state, args=(sector["GUID"], 4))
                                sector_state["irradiance_timer_on"].daemon = True
                                sector_state["irradiance_timer_on"].start()
                                sector_state["irradiance_timer_on_start"] = datetime.datetime.now()
                            elif sector_state.get("irradiance_state", 1) == 2:
                                sector_state["irradiance_state"] = 4
                                sector_state["irradiance_timer_off"].cancel()
                            elif sector_state.get("irradiance_state", 1) == 3:
                                remaining = _get_timer_interval(sector_state, "irradiance_timer_on", float('inf')) - (datetime.datetime.now() - sector_state.get("irradiance_timer_on_start", datetime.datetime.now())).total_seconds()
                                if remaining > _get_dynamic_irradiance_delay_high(sector, val):
                                    sector_state["irradiance_timer_on"].cancel()
                                    sector_state["irradiance_timer_on"] = threading.Timer(_get_dynamic_irradiance_delay_high(sector, val), SectorRunner.set_irradiance_state, args=(sector["GUID"], 4))
                                    sector_state["irradiance_timer_on"].daemon = True
                                    sector_state["irradiance_timer_on"].start()
                                    sector_state["irradiance_timer_on_start"] = datetime.datetime.now()
                            elif sector_state.get("irradiance_state", 1) == 4:
                                # Do Nothing, already in upper state
                                pass
                        elif val < _get_highest_irradiance_threshold_low(sector):
                            if sector_state.get("irradiance_state", 1) == 1:
                                # Do Nothing, already in lower state
                                pass
                            elif sector_state.get("irradiance_state", 1) == 2:
                                remaining = _get_timer_interval(sector_state, "irradiance_timer_off", float('inf')) - (datetime.datetime.now() - sector_state.get("irradiance_timer_off_start", datetime.datetime.now())).total_seconds()
                                if remaining > _get_dynamic_irradiance_delay_low(sector, val):
                                    sector_state["irradiance_timer_off"].cancel()
                                    sector_state["irradiance_timer_off"] = threading.Timer(_get_dynamic_irradiance_delay_low(sector, val), SectorRunner.set_irradiance_state, args=(sector["GUID"], 1))
                                    sector_state["irradiance_timer_off"].daemon = True
                                    sector_state["irradiance_timer_off"].start()
                                    sector_state["irradiance_timer_off_start"] = datetime.datetime.now()
                            elif sector_state.get("irradiance_state", 1) == 3:
                                sector_state["irradiance_state"] = 1
                                sector_state["irradiance_timer_on"].cancel()
                            elif sector_state.get("irradiance_state", 1) == 4:
                                sector_state["irradiance_state"] = 2
                                sector_state["irradiance_timer_off"] = threading.Timer(_get_dynamic_irradiance_delay_low(sector, val), SectorRunner.set_irradiance_state, args=(sector["GUID"], 1))
                                sector_state["irradiance_timer_off"].daemon = True
                                sector_state["irradiance_timer_off"].start()
                                sector_state["irradiance_timer_off_start"] = datetime.datetime.now()

                    else:
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
                    logger.warning("Error decoding telegram payload: %s", e)
                    return
                if sector["OnAutoBehavior"] == "Auto":
                    mode = val
                else:
                    mode = not val
                logger.info(
                    "Sector %s set to %s mode from bus",
                    sector["Name"],
                    "Auto" if mode else "On",
                )
                with SectorRunner.sectors_lock:
                    SectorRunner.sectors[sector["GUID"]]["Mode"] = "Auto" if mode else "On"

            if str(telegram.destination_address) == sector["OffAutoAddress"]:
                try:
                    val = telegram.payload.value.value == 1
                except Exception as e:
                    logger.warning("Error decoding telegram payload: %s", e)
                    return
                if sector["OffAutoBehavior"] == "Auto":
                    mode = val
                else:
                    mode = not val
                logger.info(
                    "Sector %s set to %s mode from bus",
                    sector["Name"],
                    "Auto" if mode else "Off",
                )
                with SectorRunner.sectors_lock:
                    SectorRunner.sectors[sector["GUID"]]["Mode"] = "Auto" if mode else "Off"
    except Exception as e:
        logger.exception("Error processing telegram: %s", e)
