"""Tests for the baked-in Staerium configuration defaults."""

import importlib

import pytest

import src
from src.config_loader import load_config


def test_settings_loaded_on_import() -> None:
    """The package should expose the baked-in settings object."""
    assert hasattr(src, "settings"), "settings object missing"
    assert src.settings["Version"] == "0.8.0"
    assert src.configuration.latitude == pytest.approx(47.377358)
    assert src.configuration.longitude == pytest.approx(8.519104)


def test_dynamic_variables_created_from_config() -> None:
    """Top-level config entries become uppercase module attributes."""
    # Reload to ensure a clean import context.
    importlib.reload(src)

    assert src.VERSION == "0.8.0"
    assert src.LATITUDE == pytest.approx(47.377358)
    assert src.LONGITUDE == pytest.approx(8.519104)

    sectors = src.SECTORS
    assert isinstance(sectors, list)
    assert len(sectors) == 2
    assert {sector["Name"] for sector in sectors} == {"Sektor 1", "Sektor 2"}


@pytest.mark.parametrize(
    "xml_key, attr_name",
    [("Version", "VERSION"), ("Latitude", "LATITUDE"), ("Longitude", "LONGITUDE")],
)

def test_settings_and_attributes_stay_in_sync(xml_key: str, attr_name: str) -> None:
    """Ensure mapping access and attribute access stay aligned."""
    assert getattr(src.settings, xml_key) == getattr(src, attr_name)
    assert src.settings[xml_key] == getattr(src, attr_name)


def test_repeated_nodes_convert_to_lists() -> None:
    """Sector and command collections should preserve multiple entries."""
    sectors = src.configuration.sectors
    assert isinstance(sectors, list)
    assert len(sectors) == 2

    horizon_points = sectors[0]["HorizonPoints"]
    assert isinstance(horizon_points, list)
    assert len(horizon_points) == 5

    time_programs = src.TIMEPROGRAMS
    assert isinstance(time_programs, list)
    assert len(time_programs) == 2
    assert len(time_programs[0]["Commands"]) == 3


def test_invalid_group_address_raises(tmp_path) -> None:
    """Reject group addresses outside the KNX valid range."""

    xml = tmp_path / "config.xml"
    xml.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
<Konfiguration>
  <TimeAddress>32/0/0</TimeAddress>
</Konfiguration>
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="TimeAddress"):
        load_config(xml)


def test_invalid_sector_group_address_raises(tmp_path) -> None:
    """Sector address fields must stay within KNX group address limits."""

    xml = tmp_path / "config.xml"
    xml.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
<Konfiguration>
  <Sectors>
    <Sector>
      <Name>Demo</Name>
      <BrightnessAddress>1/8/1</BrightnessAddress>
    </Sector>
  </Sectors>
</Konfiguration>
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="BrightnessAddress"):
        load_config(xml)


def test_invalid_physical_address_raises(tmp_path) -> None:
    """Reject KNX physical addresses outside the valid range."""

    xml = tmp_path / "config.xml"
    xml.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
<Konfiguration>
  <KnxIndividualAddress>16.0.0</KnxIndividualAddress>
</Konfiguration>
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="KnxIndividualAddress"):
        load_config(xml)
