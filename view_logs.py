#!/usr/bin/env python3
"""
View filtered bot logs (same filtering as dashboard but shows all lines)
Usage: python3 view_logs.py {device_name}
Example: python3 view_logs.py iPhone1
"""

import sys
import os

if len(sys.argv) < 2:
    print("Usage: python3 view_logs.py {device_name}")
    sys.exit(1)

device_name = sys.argv[1]
log_file = f"logs/{device_name}.log"

if not os.path.exists(log_file):
    print(f"Error: Log file not found: {log_file}")
    print(f"\nAvailable log files:")
    for f in os.listdir("logs"):
        if f.endswith(".log") and not f.startswith(("appium_", "iproxy_", "wda_", "dashboard_")):
            print(f"  - {f.replace('.log', '')}")
    sys.exit(1)

with open(log_file, 'r') as f:
    lines = f.readlines()

    # Apply same filtering as dashboard
    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue

        # Skip Node.js stack trace lines
        if line.startswith('    at '):
            continue

        # Skip lines with Node.js file paths
        if '/node_modules/' in line or '/opt/homebrew/' in line or '/.appium/' in line:
            continue

        # Skip lines ending with .js: and a number
        if '.js:' in line and any(c.isdigit() for c in line.split('.js:')[-1][:10]):
            continue

        # Print bot output
        print(line, end='')
