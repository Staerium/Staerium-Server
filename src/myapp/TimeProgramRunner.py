import asyncio
import datetime
import time

import pytz
from xknx.devices import NumericValue, Switch

from . import SectorRunner, configuration, sun


def start(loop):
    timezone = pytz.timezone(sun.tz)
    scheduled_commands = _build_schedule(timezone)
    if not scheduled_commands:
        print("No valid time program commands configured.")
        return

    print(f"{len(scheduled_commands)} time program command(s) scheduled.")
    while True:
        now = _current_time(timezone)
        due_commands = [entry for entry in scheduled_commands if entry["next_run"] <= now]
        for entry in due_commands:
            _dispatch_command(entry, loop, now)
            entry["next_run"] = _compute_next_run(entry, timezone, reference=now + datetime.timedelta(seconds=1))

        now = _current_time(timezone)
        next_delta = min((entry["next_run"] - now).total_seconds() for entry in scheduled_commands)
        sleep_for = max(0.05, min(next_delta, 60.0))
        time.sleep(sleep_for)


def seconds_until(then):
    now = (datetime.datetime.now(pytz.timezone(sun.tz)) - sun.timedelta)
    delta = then - now
    return delta.total_seconds()


def _current_time(tz):
    return datetime.datetime.now(tz) - sun.timedelta


def _build_schedule(timezone):
    schedule = []
    programs = getattr(configuration, "time_programs", []) or []
    if not programs:
        return schedule

    for program in programs:
        if not isinstance(program, dict):
            continue

        program_name = str(program.get("Name", "Unnamed Program"))
        commands = program.get("Commands") or []
        if not isinstance(commands, list):
            commands = [commands]

        valid = 0
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            entry = _prepare_command(program_name, command, index, timezone)
            if entry is None:
                continue
            schedule.append(entry)
            valid += 1
        print(f"Time Program: {program_name} - {valid} scheduled command{'s' if valid != 1 else ''}.")

    return schedule


def _prepare_command(program_name, command, index, timezone):
    command_type = str(command.get("Type", "1bit")).strip().lower()
    if command_type not in {"1bit", "1byte"}:
        print(f"Skipping command {program_name}#{index}: unsupported type '{command_type}'.")
        return None

    try:
        hour, minute, second = _parse_time_string(command.get("Time", "00:00"))
    except ValueError as exc:
        print(f"Skipping command {program_name}#{index}: invalid time value ({exc}).")
        return None

    weekdays = _normalize_weekdays(command.get("Weekdays"))
    if weekdays == 0:
        print(f"Skipping command {program_name}#{index}: no weekdays selected.")
        return None

    group_address = (command.get("GroupAddress") or "").strip()
    if not group_address:
        print(f"Skipping command {program_name}#{index}: missing group address.")
        return None

    try:
        value = _coerce_command_value(command_type, command.get("Value"))
    except ValueError as exc:
        print(f"Skipping command {program_name}#{index}: {exc}.")
        return None

    device_name = f"time_program_{program_name}_{index}"
    device = _build_device(command_type, group_address, device_name)

    entry = {
        "program": program_name,
        "type": command_type,
        "group_address": group_address,
        "value": value,
        "weekdays": weekdays,
        "hour": hour,
        "minute": minute,
        "second": second,
        "device": device,
        "device_name": device_name,
    }
    entry["next_run"] = _compute_next_run(entry, timezone)
    return entry


def _coerce_command_value(command_type, raw_value):
    if raw_value is None:
        raise ValueError("missing value")

    if command_type == "1bit":
        try:
            numeric = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid boolean payload") from exc
        return bool(numeric)

    try:
        numeric = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid byte payload") from exc

    if not 0 <= numeric <= 255:
        raise ValueError("byte payload must be within 0..255")
    return numeric


def _parse_time_string(time_value):
    text = str(time_value).strip()
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"unsupported time format '{text}'")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError(f"invalid numeric portion in '{text}'") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"time out of range '{text}'")

    return hour, minute, second


def _normalize_weekdays(raw_value):
    if raw_value in (None, ""):
        return 0b1111111
    try:
        mask = int(raw_value)
    except (TypeError, ValueError):
        return 0b1111111
    return mask & 0b1111111


def _build_device(command_type, group_address, device_name):
    xknx_instance = SectorRunner.xknx
    if xknx_instance is None:
        print("KNX connection not ready; command execution will be delayed.")
        return None

    if command_type == "1bit":
        device = Switch(
            xknx=xknx_instance,
            name=device_name,
            group_address=group_address,
            respond_to_read=False,
        )
    else:
        device = NumericValue(
            xknx=xknx_instance,
            name=device_name,
            group_address=group_address,
            respond_to_read=False,
            value_type=5,
        )

    xknx_instance.devices.async_add(device)
    return device


def _compute_next_run(entry, timezone, reference=None):
    now = reference or _current_time(timezone)
    for offset in range(8):  # search up to one full week
        candidate_base = now + datetime.timedelta(days=offset)
        candidate = candidate_base.replace(
            hour=entry["hour"],
            minute=entry["minute"],
            second=entry["second"],
            microsecond=0,
        )
        if candidate <= now:
            continue
        if _weekday_enabled(entry["weekdays"], candidate):
            return candidate

    return now + datetime.timedelta(days=1)


def _weekday_enabled(mask, dt_obj):
    weekday = dt_obj.weekday()  # Monday=0
    return (mask >> weekday) & 0b1 == 1


def _ensure_device(entry):
    if entry.get("device") is not None:
        return entry["device"]
    entry["device"] = _build_device(entry["type"], entry["group_address"], entry["device_name"])
    return entry["device"]


def _dispatch_command(entry, loop, timestamp):
    device = _ensure_device(entry)
    if device is None:
        if configuration.Debug:
            print(f"Skipping time program '{entry['program']}' - KNX device unavailable.")
        return

    try:
        if entry["type"] == "1bit":
            if entry["value"]:
                future = asyncio.run_coroutine_threadsafe(device.set_on(), loop)
            else:
                future = asyncio.run_coroutine_threadsafe(device.set_off(), loop)
        elif entry["type"] == "1byte":
            future = asyncio.run_coroutine_threadsafe(device.set(entry["value"]), loop)
        future.result()

        if configuration.Debug:
            print(
                f"Time program '{entry['program']}' wrote {entry['value']} "
                f"to {entry['group_address']} at {timestamp.isoformat()}"
            )
    except Exception as exc:  # pragma: no cover - transport errors are environment dependent
        print(
            f"Failed to execute time program '{entry['program']}' "
            f"for {entry['group_address']}: {exc}"
        )
