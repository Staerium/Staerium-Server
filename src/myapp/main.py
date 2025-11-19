"""Entry point for Staerium Server application."""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from typing import Any
from xknx import XKNX
from xknx.io import ConnectionConfig, ConnectionType
import threading
import psutil
import ipaddress as ip


from . import configuration  # type: ignore
from . import SectorRunner
from . import KNX
from . import check_time
from . import TimeProgramRunner


try:
    from . import settings  # type: ignore
except ImportError:
    if __package__ in {None, ""}:
        package_root = Path(__file__).resolve().parent.parent
        if str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))
        import myapp  # type: ignore

        settings = myapp.settings  # noqa: F401 ensures eager load
    else:
        raise


def get_local_ip(host, port) -> str:
    """Best-effort detection of the primary IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Non-routable TEST-NET-2 address avoids real traffic.
            sock.connect((host, port))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def same_subnet(source, target) -> bool:
    # find matching interface address and netmask
    for iface_addrs in psutil.net_if_addrs().values():
        for a in iface_addrs:
            if a.family == socket.AF_INET and a.address == source:
                net = ip.ip_network(f"{a.address}/{a.netmask}", strict=False)
                return ip.ip_address(target) in net


async def connect_knx() -> Any:
    """Initialise an xKNX instance and establish a gateway connection."""

    connection_type_name = str(configuration.knx_connection_type).upper()
    try:
        connection_type = ConnectionType[connection_type_name]
    except KeyError as exc:
        valid_types = ", ".join(sorted(ct.name for ct in ConnectionType))
        raise ValueError(
            f"Unsupported KNX connection type '{connection_type_name}'."
            f" Valid options: {valid_types}."
        ) from exc

    if connection_type in {ConnectionType.TUNNELING, ConnectionType.TUNNELING_TCP}:
        print(f"Connecting to KNX gateway at {configuration.knx_gateway_ip}:{configuration.knx_gateway_port} ...")
        connection_config = ConnectionConfig(
            connection_type=connection_type,
            individual_address=configuration.knx_individual_address,
            gateway_ip=configuration.knx_gateway_ip,
            gateway_port=configuration.knx_gateway_port,
            local_ip=configuration.ip_address_knx if same_subnet(configuration.knx_gateway_ip, configuration.ip_address_knx) else None,
            multicast_group=configuration.knx_multicast_group,
            multicast_port=configuration.knx_multicast_port,
            auto_reconnect=configuration.knx_auto_reconnect,
            auto_reconnect_wait=configuration.knx_auto_reconnect_wait,
        )
    else:
        print(f"Connecting to KNX gateway at {configuration.knx_multicast_group}:{configuration.knx_multicast_port} ...")
        connection_config = ConnectionConfig(
            connection_type=connection_type,
            individual_address=configuration.knx_individual_address,
            local_ip=configuration.ip_address_knx,
            multicast_group=configuration.knx_multicast_group,
            multicast_port=configuration.knx_multicast_port,
            auto_reconnect=configuration.knx_auto_reconnect,
            auto_reconnect_wait=configuration.knx_auto_reconnect_wait,
        )

    SectorRunner.xknx = XKNX(connection_config=connection_config, daemon_mode=False, telegram_received_cb=KNX.telegram_received)
    try:
        await SectorRunner.xknx.start()
        return SectorRunner.xknx
    except Exception as e:
        print(f"Error connecting to KNX: {e}, retrying... in {configuration.knx_auto_reconnect_wait} seconds")
        started = False
        while not started and configuration.knx_auto_reconnect:
            await asyncio.sleep(configuration.knx_auto_reconnect_wait)
            try:
                await SectorRunner.xknx.start()
                started = True
                return SectorRunner.xknx
            except Exception as e:
                print(f"Reconnection failed: {e}, retrying... in {configuration.knx_auto_reconnect_wait} seconds")
        return None


async def _async_main() -> None:
    """Async CLI entry point handling KNX connection lifecycle."""
    if not configuration.version in {"0.9.3", "0.9.2", "0.9.1", "0.9.0", "0.8.0"}:
        print(f"Conficuration version: {configuration.version} is not supported by this Staerium Server version - please update your configuration file or staerium server installation.")
        print("Exiting...")
        return
    configuration.ip_address_knx = get_local_ip(configuration.knx_gateway_ip, configuration.knx_gateway_port)
    configuration.ip_address_internet = get_local_ip("8.8.8.8", 53)
    print(f"Server IP (KNX communication): {configuration.ip_address_knx}")
    print(f"Server IP (Internet communication): {configuration.ip_address_internet}")
    # TODO: Print IP for API

    knx: XKNX | None = None
    try:
        knx = await connect_knx()
        if knx is None:
            print(
                "Unable to establish a KNX connection. "
                "Please verify the gateway settings and try again."
            )
            return

        print("Connected to KNX gateway.")

        # Check if Time is correct (Check with NTP)
        if configuration.az_el_option == "Internet":
            await check_time.check_system_time(threshold_seconds=60)

        # Start SectorRunner in background so it doesn't block the event loop.
        loop = asyncio.get_running_loop()
        SectorRunnerThread = threading.Thread(name='SectorRunner', args=(loop,), target=SectorRunner.start, daemon=True)
        SectorRunnerThread.start()
        TimeProgramRunnerThread = threading.Thread(name='TimeProgramRunner', args=(loop,), target=TimeProgramRunner.start, daemon=True)
        TimeProgramRunnerThread.start()
        print("Welcome to Staerium Server!")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
    finally:
        if knx is not None:
            await knx.stop()
            print("KNX connection closed.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
