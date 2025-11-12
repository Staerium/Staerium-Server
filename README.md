# Staerium Server

Staerium Server is a Python service that monitors sun position and KNX bus telemetry to automate façade sectors. The application can run directly on a host system or inside the provided Docker container and relies on an XML configuration file that mirrors the Staerium Sun Project export format.

## Requirements
- Python 3.10 or newer (the Docker image uses 3.12)
- pip 23+
- Access to a KNX/IP interface or router
- An exported Staerium XML configuration (`config.xml` / `.sunproj`)

## Quick Start
1. **Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
2. **Provide configuration**
   - Use the sample at `src/myapp/config.xml`, or
   - Replace it with your own export (keep the same filename or adjust `config_loader.load_config` to read another path).
3. **Run the server**
   ```bash
   export PYTHONPATH=src
   python -m myapp.main
   ```
   The process prints the detected IP addresses, synchronises time (if enabled) and starts the KNX listeners plus the sector and time-program worker threads.

## Docker / Compose
Build and run the container without touching the host Python installation:
```bash
docker compose up --build
```
The compose definition builds from the local Dockerfile, runs the service as the non-root `appuser`, and can be extended with volume mounts for configuration or logs.

## Configuration
- `src/myapp/config.xml` contains the baked-in defaults used for tests and development.
- `configuration.sunproj` is an alternate export kept for reference.
- `src/myapp/config_loader.py` parses and validates KNX addressing, ensuring every group and physical address stays within the KNX specification.
- Adjust operational settings (gateway IPs, reconnection policy, azimuth/elevation options, sectors, time programs) either by editing the XML or by providing your own file at runtime.

## Testing
Run the unit test suite (after installing `pytest` via `requirements.txt`):
```bash
PYTHONPATH=src python -m pytest
```
The tests cover configuration loading and the CLI entry point. Add targeted tests for KNX telegram handling, sector logic, and the time-program scheduler as you extend the project.

## Project Layout
- `src/myapp/` – Application packages (`main`, configuration helpers, KNX handlers, sector/time program runners, solar calculations).
- `tests/` – Pytest suite.
- `requirements.txt` – Runtime + developer dependencies.
- `Dockerfile` / `compose.yml` – Container build and deployment descriptors.
- `licenses.txt` – Project license guidance and third-party notices.

## Licensing
See `licenses.txt` for guidance on selecting a project license and the upstream licenses for bundled dependencies.
