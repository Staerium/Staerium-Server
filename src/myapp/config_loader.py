"""Utilities for loading and normalising Staerium XML configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


FORCED_LIST_TAGS = frozenset({"Sector", "TimeProgram", "Command", "Point"})


def _normalise_address_value(value: Any) -> str | None:
    """Return a trimmed string for address validation or ``None`` if empty."""

    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        return text or None

    text = str(value).strip()
    return text or None


def _validate_group_address(value: Any, context: str, *, allow_empty: bool = True) -> str:
    """Ensure KNX group addresses stay within <0-31>/<0-7>/<0-255>."""

    normalised = _normalise_address_value(value)
    if normalised is None:
        if allow_empty:
            return ""
        raise ValueError(f"Missing group address for {context}")

    parts = normalised.split("/")
    if len(parts) != 3:
        raise ValueError(f"Invalid group address for {context}: {value!r}")

    try:
        main, middle, sub = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"Group address segments must be integers for {context}: {value!r}") from exc

    if not 0 <= main <= 31:
        raise ValueError(f"Group address main field out of range for {context}: {main}")
    if not 0 <= middle <= 7:
        raise ValueError(f"Group address middle field out of range for {context}: {middle}")
    if not 0 <= sub <= 255:
        raise ValueError(f"Group address sub field out of range for {context}: {sub}")

    return normalised


def _validate_physical_address(value: Any, context: str, *, allow_empty: bool = True) -> str:
    """Ensure KNX physical addresses stay within <0-15>.<0-15>.<0-255>."""

    normalised = _normalise_address_value(value)
    if normalised is None:
        if allow_empty:
            return ""
        raise ValueError(f"Missing physical address for {context}")

    parts = normalised.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid physical address for {context}: {value!r}")

    try:
        area, line, device = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"Physical address segments must be integers for {context}: {value!r}") from exc

    if not 0 <= area <= 15:
        raise ValueError(f"Physical address area field out of range for {context}: {area}")
    if not 0 <= line <= 15:
        raise ValueError(f"Physical address line field out of range for {context}: {line}")
    if not 0 <= device <= 255:
        raise ValueError(f"Physical address device field out of range for {context}: {device}")

    return normalised


def _validate_config_addresses(config: dict[str, Any]) -> None:
    """Apply KNX address validations after normalising structure."""

    config["TimeAddress"] = _validate_group_address(config.get("TimeAddress"), "TimeAddress")
    config["AzimuthAddress"] = _validate_group_address(config.get("AzimuthAddress"), "AzimuthAddress")
    config["ElevationAddress"] = _validate_group_address(config.get("ElevationAddress"), "ElevationAddress")
    config["KnxIndividualAddress"] = _validate_physical_address(
        config.get("KnxIndividualAddress"), "KnxIndividualAddress"
    )

    sectors = config.get("Sectors", [])
    if isinstance(sectors, list):
        for index, sector in enumerate(sectors):
            if not isinstance(sector, dict):
                continue

            sector_name = sector.get("Name")
            context_prefix = f"Sector '{sector_name}'" if sector_name else f"Sectors[{index}]"

            for key, value in list(sector.items()):
                if key.endswith("Address"):
                    sector[key] = _validate_group_address(value, f"{context_prefix}.{key}")

    programs = config.get("TimePrograms", [])
    if isinstance(programs, list):
        for program_index, program in enumerate(programs):
            if not isinstance(program, dict):
                continue

            commands = program.get("Commands")
            if not isinstance(commands, list):
                continue

            for command_index, command in enumerate(commands):
                if not isinstance(command, dict):
                    continue

                context = (
                    f"TimePrograms[{program_index}].Commands[{command_index}].GroupAddress"
                )
                command["GroupAddress"] = _validate_group_address(
                    command.get("GroupAddress"), context
                )

def load_config(xml_path: str | Path | None = None) -> dict[str, Any]:
    """Parse the Staerium XML config into native Python structures."""

    path = Path(xml_path) if xml_path is not None else Path(__file__).with_name("config.xml")

    # path = Path("/configuration.sunproj")

    tree = ET.parse(path)
    root = tree.getroot()
    config = _parse_element(root)

    config["Sectors"] = _normalise_sectors(config.get("Sectors"))
    config["TimePrograms"] = _normalise_time_programs(config.get("TimePrograms"))

    _validate_config_addresses(config)

    return config


def _normalise_sectors(raw_value: Any) -> list[dict[str, Any]]:
    sectors = _extract_sequence(raw_value, "Sector")
    normalised: list[dict[str, Any]] = []
    for sector in sectors:
        if isinstance(sector, dict):
            horizon_points = sector.get("HorizonPoints")
            if horizon_points is not None:
                sector["HorizonPoints"] = _extract_sequence(horizon_points, "Point")

            ceiling_points = sector.get("CeilingPoints")
            if ceiling_points is not None:
                sector["CeilingPoints"] = _extract_sequence(ceiling_points, "Point")

        normalised.append(sector)

    return normalised


def _normalise_time_programs(raw_value: Any) -> list[dict[str, Any]]:
    programs = _extract_sequence(raw_value, "TimeProgram")
    for program in programs:
        if isinstance(program, dict) and "Commands" in program:
            program["Commands"] = _extract_sequence(program["Commands"], "Command")
    return programs


def _extract_sequence(value: Any, child_key: str) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        child = value.get(child_key)
        if isinstance(child, list):
            return child
        if child is not None:
            return [child]

    return [value]


def _parse_element(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return _convert_text(element.text)

    grouped: dict[str, list[Any]] = {}
    for child in children:
        value = _parse_element(child)
        grouped.setdefault(child.tag, []).append(value)

    result: dict[str, Any] = {}
    for tag, values in grouped.items():
        if len(values) > 1 or tag in FORCED_LIST_TAGS:
            result[tag] = values
        else:
            result[tag] = values[0]

    return result


def _convert_text(text: str | None) -> Any:
    if text is None:
        return ""

    value = text.strip()
    if not value:
        return ""

    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        if value.startswith("0") and value not in {"0", "0.0"} and not value.startswith("0."):
            raise ValueError
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


__all__ = ["load_config"]
