# Staerium Server

Staerium Server is a Python KNX service that reads Staerium Configurator exports and drives facade shading. It can calculate sun position itself (pvlib) or consume azimuth/elevation from the bus, then publishes KNX telegrams for sun state, height, louvre tracking, and scheduled time programs. Run it directly or via the supplied Docker image.

## Requirements
- Python 3.10+ (Docker image uses 3.12)
- pip 23+
- KNX/IP interface or router (tunnelling or routing)
- Staerium Configurator export (`.sunproj`)

## Configuration
- Place your config at `src/myapp/config.xml` (Compose mounts to the same path). The runtime accepts config versions `1.0.0` or `0.9.0`–`0.9.6` and aborts otherwise.
- Parsed by `src/myapp/config_loader.py`, which normalises repeated nodes into lists and validates KNX group (0–31/0–7/0–255) and physical (0–15.0–15.0–255) addresses.
- Key options:
  - Coordinates: `Latitude`, `Longitude`, `AzElTimezone`.
  - Az/El source (`AzElOption`): `Internet` (pvlib with NTP check), `BusTime` (pvlib using time from `TimeAddress`/`DateAddress`), or `BusAzEl` (azimuth/elevation read from `AzimuthAddress`/`ElevationAddress` with DPT 5.003/8.011/14.007).
  - KNX connection: `KnxConnectionType` (`TUNNELING`, `TUNNELING_TCP`, `ROUTING`), gateway/multicast settings, `KnxIndividualAddress`, `KnxAutoReconnect`, `KnxAutoReconnectWait`.
  - Sectors: orientation, horizon/ceiling points to clip the sun, brightness and irradiance inputs with thresholds/delays, mode toggles via `OnAutoAddress`/`OffAutoAddress`, optional `SunBoolAddress`, `HeightAddress`, `LouvreAngleAddress`, and louvre geometry (`LouvreTracking`, spacing/depth/angle limits, minimum change, buffer).
  - Time programs: commands with `Type` (`1bit`/`1byte`), `Weekdays` bitmask (Mon is bit 0), `Time` (`HH:MM[:SS]`), payload `Value`, and `GroupAddress`.

## Run locally (not recommended)
1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install --upgrade pip && pip install -r requirements.txt`
3. Drop your supported Staerium export at `src/myapp/config.xml` (or point `config_loader.load_config` to another path).
4. `export PYTHONPATH=src`
5. `python -m myapp.main`

Startup prints detected IPs, connects to the KNX gateway (with optional auto-reconnect), checks time via NTP when using `AzElOption=Internet`, then starts the KNX listener plus sector and time-program threads.

## Docker / Compose
- Edit `compose.yml` to mount your config to `/app/src/myapp/config.xml:ro`.
- Run `docker compose up -d` (uses `ericstaedler/staerium-server:latest`) or `docker compose up --build` to build locally.
- Logs: `docker compose logs -f StaeriumServer`; restart the service to pick up config changes.

## Runtime behaviour
- Sun position: pvlib calculation unless `AzElOption=BusAzEl`; BusTime mode offsets pvlib timestamps using bus-supplied date/time.
- Sector control: brightness/irradiance telegrams toggle sun state with thresholds and delays; facade only marked lit when azimuth is within ±90° of sector orientation and elevation passes horizon/ceiling curves; optional louvre tracking writes 0–255 angle updates; mode can be forced via On/Off auto addresses.
- Time programs: scheduled KNX writes run in the configured timezone, honour the bus time offset, and send either 1-bit on/off or 1-byte values.

## Licensing
See `LICENSE.txt`.