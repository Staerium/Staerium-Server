"""Tests for the Staerium main module interactions."""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest

sys.modules.setdefault("configuration", importlib.import_module("src.configuration"))
sys.modules.setdefault("sun", importlib.import_module("src.sun"))
sys.modules.setdefault("SectorRunner", importlib.import_module("src.SectorRunner"))
sys.modules.setdefault("KNX", importlib.import_module("src.KNX"))
sys.modules.setdefault("check_time", importlib.import_module("src.check_time"))

import src.main as main_module


def test_get_local_ip_handles_errors(monkeypatch) -> None:
    """Fallback to loopback when socket discovery fails."""
    module = importlib.reload(main_module)

    def fail_socket(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(module.socket, "socket", fail_socket)
    assert module.get_local_ip("example.com", 1234) == "127.0.0.1"


def test_get_local_ip_returns_detected_address(monkeypatch) -> None:
    """Return the interface IP reported by the socket."""
    module = importlib.reload(main_module)

    class DummySocket:
        def __enter__(self) -> "DummySocket":
            return self

        def __exit__(self, *_exc) -> None:  # pragma: no cover - nothing to clean up
            return None

        def connect(self, _target) -> None:
            return None

        def getsockname(self) -> tuple[str, int]:
            return ("203.0.113.5", 9999)

    monkeypatch.setattr(module.socket, "socket", lambda *_args, **_kwargs: DummySocket())
    assert module.get_local_ip("staerium.local", 3671) == "203.0.113.5"


def test_connect_knx_builds_tunneling_config(monkeypatch) -> None:
    """Ensure tunnelling configuration parameters are forwarded to xKNX."""
    module = importlib.reload(main_module)

    monkeypatch.setattr(module.configuration, "knx_connection_type", "tunneling")
    monkeypatch.setattr(module.configuration, "knx_individual_address", "1.1.10")
    monkeypatch.setattr(module.configuration, "knx_gateway_ip", "192.0.2.5")
    monkeypatch.setattr(module.configuration, "knx_gateway_port", 4242)
    monkeypatch.setattr(module.configuration, "ip_address_knx", "192.0.2.100")
    monkeypatch.setattr(module.configuration, "knx_multicast_group", "224.0.23.12")
    monkeypatch.setattr(module.configuration, "knx_multicast_port", 3671)
    monkeypatch.setattr(module.configuration, "knx_auto_reconnect", False)
    monkeypatch.setattr(module.configuration, "knx_auto_reconnect_wait", 5)

    captured: dict[str, object] = {}

    class DummyConfig:
        def __init__(self, **kwargs) -> None:
            captured["config_kwargs"] = kwargs

    class DummyKnx:
        def __init__(self, *, connection_config, daemon_mode, telegram_received_cb):
            captured["connection_config"] = connection_config
            captured["daemon_mode"] = daemon_mode
            captured["telegram_cb"] = telegram_received_cb

        async def start(self) -> None:
            captured["started"] = True

        async def stop(self) -> None:
            captured["stopped"] = True

    monkeypatch.setattr(module, "ConnectionConfig", DummyConfig)
    monkeypatch.setattr(module, "XKNX", DummyKnx)

    knx = asyncio.run(module.connect_knx())

    assert isinstance(knx, DummyKnx)
    assert captured["started"] is True
    config_kwargs = captured["config_kwargs"]
    assert config_kwargs["connection_type"] is module.ConnectionType.TUNNELING
    assert config_kwargs["individual_address"] == "1.1.10"
    assert config_kwargs["gateway_ip"] == "192.0.2.5"
    assert config_kwargs["gateway_port"] == 4242
    assert config_kwargs["local_ip"] == "192.0.2.100"
    assert config_kwargs["multicast_group"] == "224.0.23.12"
    assert config_kwargs["multicast_port"] == 3671
    assert config_kwargs["auto_reconnect"] is False
    assert config_kwargs["auto_reconnect_wait"] == 5
    assert captured["daemon_mode"] is False
    assert captured["telegram_cb"] is module.KNX.telegram_received


def test_connect_knx_rejects_unknown_type(monkeypatch) -> None:
    """Invalid connection types should surface a clear error."""
    module = importlib.reload(main_module)

    monkeypatch.setattr(module.configuration, "knx_connection_type", "invalid-type")

    with pytest.raises(ValueError, match="Unsupported KNX connection type"):
        asyncio.run(module.connect_knx())


def test_async_main_outputs_expected_messages(monkeypatch, capsys) -> None:
    """Verify the happy-path startup, time sync, and shutdown flow."""
    module = importlib.reload(main_module)

    monkeypatch.setattr(module.configuration, "knx_gateway_ip", "10.1.2.3")
    monkeypatch.setattr(module.configuration, "knx_gateway_port", 5678)
    monkeypatch.setattr(module.configuration, "az_el_option", "Internet")
    monkeypatch.setattr(module.configuration, "knx_auto_reconnect", False)
    monkeypatch.setattr(module.configuration, "knx_auto_reconnect_wait", 1)
    monkeypatch.setattr(module.configuration, "ip_address_knx", "0.0.0.0")
    monkeypatch.setattr(module.configuration, "ip_address_internet", "0.0.0.0")

    responses = {
        ("10.1.2.3", 5678): "192.0.2.10",
        ("8.8.8.8", 53): "198.51.100.20",
    }
    local_calls: list[tuple[str, int]] = []

    def fake_get_local_ip(host: str, port: int) -> str:
        local_calls.append((host, port))
        return responses[(host, port)]

    state: dict[str, object] = {}

    class DummyKnx:
        async def stop(self) -> None:
            state["stopped"] = True

    async def fake_connect_knx() -> DummyKnx:
        state["connected"] = True
        return DummyKnx()

    async def fake_check_time(*, threshold_seconds: int) -> None:
        state["check_time"] = threshold_seconds

    def cancelled_future() -> asyncio.Future[None]:
        future = asyncio.get_running_loop().create_future()
        future.cancel()
        return future

    monkeypatch.setattr(module, "get_local_ip", fake_get_local_ip)
    monkeypatch.setattr(module, "connect_knx", fake_connect_knx)
    monkeypatch.setattr(module.check_time, "check_system_time", fake_check_time)
    monkeypatch.setattr(module.asyncio, "Future", cancelled_future)

    asyncio.run(module._async_main())

    captured = capsys.readouterr()
    assert "Server IP (KNX communication): 192.0.2.10" in captured.out
    assert "Server IP (Internet communication): 198.51.100.20" in captured.out
    assert "Connecting to KNX gateway at 10.1.2.3:5678 ..." in captured.out
    assert "Connected to KNX gateway." in captured.out
    assert "Welcome to Staerium Server!" in captured.out
    assert "KNX connection closed." in captured.out

    assert local_calls == [("10.1.2.3", 5678), ("8.8.8.8", 53)]
    assert module.configuration.ip_address_knx == "192.0.2.10"
    assert module.configuration.ip_address_internet == "198.51.100.20"
    assert state["connected"] is True
    assert state["stopped"] is True
    assert state["check_time"] == 60
