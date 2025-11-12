from typing import Any
from collections.abc import Mapping
import sys
from pathlib import Path


try:
    from myapp import settings
except ImportError:
    if __package__ in {None, ""}:
        package_root = Path(__file__).resolve().parent.parent
        if str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))
        import myapp  # type: ignore

        settings = myapp.settings  # noqa: F401 ensures eager load
    else:
        raise

def _get_setting(source: Any, key: str, default: Any = None) -> Any:
    """Retrieve a configuration value from either mapping or attribute sources."""
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


ip_address_knx = "127.0.0.1"
ip_address_internet = "127.0.0.1"

Debug = False #TODO: deactivate for production


#imported from config
latitude = _get_setting(settings, "Latitude")
longitude = _get_setting(settings, "Longitude")
az_el_option = _get_setting(settings, "AzElOption", "Internet")
time_address = _get_setting(settings, "TimeAddress")
date_address = _get_setting(settings, "DateAddress")
azimuth_address = _get_setting(settings, "AzimuthAddress")
elevation_address = _get_setting(settings, "ElevationAddress")
azimuth_dpt = _get_setting(settings, "AzimuthDPT", "5.003")
elevation_dpt = _get_setting(settings, "ElevationDPT", "5.003")
az_el_timezone = _get_setting(settings, "AzElTimezone", "Europe/Zurich")
knx_connection_type = _get_setting(settings, "KnxConnectionType", "TUNNELING")
knx_individual_address = _get_setting(settings, "KnxIndividualAddress", "15.15.255")
knx_gateway_ip = _get_setting(settings, "KnxGatewayIp", "127.0.0.1")
knx_gateway_port = _get_setting(settings, "KnxGatewayPort", 3671)
knx_multicast_group = _get_setting(settings, "KnxMulticastGroup", "224.0.23.12")
knx_multicast_port = _get_setting(settings, "KnxMulticastPort", 3671)
knx_auto_reconnect = _get_setting(settings, "KnxAutoReconnect", True)
knx_auto_reconnect_wait = _get_setting(settings, "KnxAutoReconnectWait", 5)
sectors = _get_setting(settings, "Sectors")
time_programs = _get_setting(settings, "TimePrograms")