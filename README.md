# Instagram Bot - Multi-Device

Automated Instagram account creation bot for multiple iOS devices.

## Quick Start

1. **Start the dashboard:**
   ```bash
   python3 dashboard.py
   ```

2. **Open browser:** http://localhost:5000

3. **Click Start** on any device to begin

## Main Files

- `dashboard.py` - Web dashboard (start this)
- `run_device.py` - Bot automation script
- `accounts.txt` - Created accounts storage
- `devices.json` - Device configuration
- `requirements.txt` - Python dependencies

## Folders

- `logs/` - Runtime logs
- `templates/` - HTML templates
- `static/` - CSS/JS assets
- `docs/` - Documentation
- `scripts/` - Utility scripts
- `archive/` - Old/unused files

## How It Works

When you click "Start" on a device:
1. Starts iproxy (port forwarding)
2. Launches WebDriverAgent on device
3. Starts Appium server
4. Runs Instagram bot automation
5. Creates accounts and saves to accounts.txt

Each device runs independently with isolated processes.
