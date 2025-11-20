#!/usr/bin/env python3
"""
Simple Web Dashboard for Multi-Device Instagram Bot
Run on http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request
import json
import subprocess
import os
import signal
import time
import requests
import atexit
import sys
from datetime import datetime

app = Flask(__name__)

# Store running processes by UDID for reliability (not affected by index changes)
processes = {}  # {udid: {'iproxy': process, 'wda': process, 'appium': process, 'bot': process}}

# Store device stats (resets when dashboard restarts)
device_stats = {}  # {device_index: {'successful': 0, 'confirm_human': 0, 'failed': 0}}

# Store detailed device stats (resets when dashboard restarts)
detailed_stats = {}  # {device_index: {'successful': {'first_request': 0, 'second_request': 0, 'multiple_numbers': 0}, 'confirm_human': {...}}}

# Flag to prevent multiple cleanup calls
_cleanup_in_progress = False

CONFIG_FILE = 'devices.json'
LOGS_DIR = 'logs'
WDA_DIR = '/Users/kevinpencu/Downloads/WebDriverAgent'

# IP rotation mode: 'potatso' or 'mobile_data'
IP_ROTATION_MODE = 'potatso'  # Default to potatso


def load_config():
    """Load devices configuration"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'devices': [], 'shared_config': {}}


def save_config(config):
    """Save devices configuration"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_next_ports(config):
    """Get next available ports for a new device"""
    if not config['devices']:
        return 6001, 8100, 8200, 9100

    last_device = config['devices'][-1]
    return (
        last_device['appium_port'] + 1,
        last_device['wda_local_port'] + 1,
        last_device['system_port'] + 1,
        last_device['mjpeg_port'] + 1
    )


def cleanup_large_logs(max_size_mb=100):
    """Delete log files larger than max_size_mb to prevent storage exhaustion"""
    if not os.path.exists(LOGS_DIR):
        return

    deleted_count = 0
    freed_space_mb = 0

    try:
        for filename in os.listdir(LOGS_DIR):
            if filename.endswith('.log'):
                filepath = os.path.join(LOGS_DIR, filename)
                try:
                    size_mb = os.path.getsize(filepath) / (1024 * 1024)
                    if size_mb > max_size_mb:
                        os.remove(filepath)
                        deleted_count += 1
                        freed_space_mb += size_mb
                        print(f"  Deleted large log: {filename} ({size_mb:.1f} MB)")
                except Exception as e:
                    print(f"  Warning: Could not process {filename}: {e}")

        if deleted_count > 0:
            print(f"✓ Cleaned up {deleted_count} large log file(s), freed {freed_space_mb:.1f} MB")
    except Exception as e:
        print(f"Warning: Log cleanup error (non-fatal): {e}")


def start_appium(port, device_name):
    """Start Appium server for a device"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = open(f"{LOGS_DIR}/appium_{port}.log", "w")

    try:
        process = subprocess.Popen(
            ["appium", "-p", str(port), "--base-path", "/wd/hub"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        return process
    except Exception as e:
        print(f"Failed to start Appium: {e}")
        return None


def start_bot(device_index, device_name):
    """Start bot for a device"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    # Open log file with line buffering (buffering=1) so logs appear immediately
    log_file = open(f"{LOGS_DIR}/{device_name}.log", "w", buffering=1)

    try:
        # Set PYTHONUNBUFFERED to ensure print statements appear immediately
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'

        process = subprocess.Popen(
            ["python3", "-u", "run_device.py", "--device-index", str(device_index), "--ip-mode", IP_ROTATION_MODE],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env
        )
        # Return both process and log file handle (to keep it alive)
        return process, log_file
    except Exception as e:
        print(f"Failed to start bot: {e}")
        log_file.close()
        return None, None


def stop_process(process):
    """Stop a process gracefully"""
    if process and process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
        except:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except:
                pass


def start_iproxy(device):
    """Start iproxy for port forwarding (Mac port -> device port 8100)"""
    udid = device['udid']
    host_port = device['wda_local_port']
    device_name = device['name']

    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = open(f"{LOGS_DIR}/iproxy_{device_name}.log", "w")

    # Kill any existing iproxy on this port
    try:
        subprocess.run(f"lsof -ti:{host_port} | xargs kill -9", shell=True, capture_output=True)
        time.sleep(1)
    except:
        pass

    try:
        process = subprocess.Popen(
            ["iproxy", "--udid", udid, str(host_port), "8100"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        print(f"Started iproxy for {device_name}: localhost:{host_port} -> device:8100")
        return process
    except Exception as e:
        print(f"Failed to start iproxy for {device_name}: {e}")
        return None


def start_wda_xcodebuild(device):
    """Start WDA on device using xcodebuild"""
    udid = device['udid']
    device_name = device['name']

    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = open(f"{LOGS_DIR}/wda_{device_name}.log", "w")

    # Isolated DerivedData per device
    derived_data = f"/tmp/wda-{udid}"

    try:
        process = subprocess.Popen(
            [
                "xcodebuild",
                "-project", f"{WDA_DIR}/WebDriverAgent.xcodeproj",
                "-scheme", "WebDriverAgentRunner",
                "-configuration", "Debug",
                "-destination", f"id={udid}",
                "-derivedDataPath", derived_data,
                "-allowProvisioningUpdates",
                "test"
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=WDA_DIR
        )
        print(f"Started WDA xcodebuild for {device_name}")
        return process
    except Exception as e:
        print(f"Failed to start WDA for {device_name}: {e}")
        return None


def wait_for_wda(wda_port, timeout=60):
    """Wait for WDA to be ready by polling /status endpoint"""
    url = f"http://127.0.0.1:{wda_port}/status"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                print(f"WDA ready on port {wda_port}")
                return True
        except:
            pass
        time.sleep(2)

    print(f"WDA timeout on port {wda_port}")
    return False


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')


@app.route('/api/devices')
def get_devices():
    """Get all devices with their status"""
    config = load_config()
    devices_with_status = []

    for idx, device in enumerate(config['devices']):
        status = 'stopped'
        udid = device['udid']

        # Check by UDID, not index
        if udid in processes:
            proc_info = processes[udid]
            iproxy_running = proc_info.get('iproxy') and proc_info['iproxy'].poll() is None
            wda_running = proc_info.get('wda') and proc_info['wda'].poll() is None
            appium_running = proc_info.get('appium') and proc_info['appium'].poll() is None
            bot_running = proc_info.get('bot') and proc_info['bot'].poll() is None

            if bot_running and appium_running:
                status = 'running'
            elif iproxy_running or wda_running or appium_running:
                status = 'starting'

        # Get stats for this device (default to zeros if not exists)
        stats = device_stats.get(idx, {'successful': 0, 'confirm_human': 0, 'failed': 0})

        devices_with_status.append({
            'index': idx,
            'name': device['name'],
            'udid': device['udid'],
            'appium_port': device['appium_port'],
            'status': status,
            'stats': stats
        })

    return jsonify(devices_with_status)


@app.route('/api/device/add', methods=['POST'])
def add_device():
    """Add a new device"""
    data = request.json
    config = load_config()

    # Get next available ports
    appium_port, wda_port, system_port, mjpeg_port = get_next_ports(config)

    new_device = {
        'name': data['name'],
        'udid': data['udid'],
        'appium_port': appium_port,
        'wda_local_port': wda_port,
        'system_port': system_port,
        'mjpeg_port': mjpeg_port
    }

    config['devices'].append(new_device)
    save_config(config)

    return jsonify({'success': True, 'device': new_device})


@app.route('/api/device/<int:device_index>/delete', methods=['POST'])
def delete_device(device_index):
    """Delete a device"""
    config = load_config()

    if device_index >= len(config['devices']):
        return jsonify({'success': False, 'error': 'Device not found'}), 404

    device = config['devices'][device_index]
    udid = device['udid']

    # Stop if running
    if udid in processes:
        stop_device(device_index)

    del config['devices'][device_index]
    save_config(config)
    return jsonify({'success': True})


@app.route('/api/device/<int:device_index>/start', methods=['POST'])
def start_device(device_index):
    """Start a device with WDA, iproxy, Appium, and bot"""
    config = load_config()

    if device_index >= len(config['devices']):
        return jsonify({'success': False, 'error': 'Device not found'}), 404

    device = config['devices'][device_index]

    print(f"\n{'='*60}")
    print(f"Starting {device['name']}...")
    print(f"{'='*60}")

    # Step 0: Clean up large log files to prevent storage exhaustion
    print(f"[0/5] Cleaning up large log files...")
    cleanup_large_logs(max_size_mb=100)

    # Step 1: Start iproxy (port forwarding)
    print(f"[1/5] Starting iproxy...")
    iproxy_process = start_iproxy(device)
    if not iproxy_process:
        return jsonify({'success': False, 'error': 'Failed to start iproxy'}), 500
    time.sleep(2)

    # Step 2: Start WDA via xcodebuild
    print(f"[2/5] Starting WDA on device...")
    wda_process = start_wda_xcodebuild(device)
    if not wda_process:
        stop_process(iproxy_process)
        return jsonify({'success': False, 'error': 'Failed to start WDA'}), 500

    # Step 3: Wait for WDA to be ready
    print(f"[3/5] Waiting for WDA to be ready...")
    if not wait_for_wda(device['wda_local_port'], timeout=90):
        stop_process(wda_process)
        stop_process(iproxy_process)
        return jsonify({'success': False, 'error': 'WDA failed to start (timeout)'}), 500

    # Step 4: Start Appium server
    print(f"[4/5] Starting Appium server...")
    appium_process = start_appium(device['appium_port'], device['name'])
    if not appium_process:
        stop_process(wda_process)
        stop_process(iproxy_process)
        return jsonify({'success': False, 'error': 'Failed to start Appium'}), 500
    time.sleep(5)

    # Step 5: Start bot
    print(f"[5/5] Starting bot...")
    bot_process, bot_log_file = start_bot(device_index, device['name'])
    if not bot_process:
        stop_process(appium_process)
        stop_process(wda_process)
        stop_process(iproxy_process)
        return jsonify({'success': False, 'error': 'Failed to start bot'}), 500

    # Store all processes by UDID (not index, for reliability)
    processes[device['udid']] = {
        'iproxy': iproxy_process,
        'wda': wda_process,
        'appium': appium_process,
        'bot': bot_process,
        'bot_log_file': bot_log_file,  # Keep log file handle alive
        'device_index': device_index,
        'started_at': datetime.now().isoformat()
    }

    print(f"✅ {device['name']} started successfully!")
    print(f"{'='*60}\n")

    return jsonify({'success': True})


@app.route('/api/device/<int:device_index>/stop', methods=['POST'])
def stop_device(device_index):
    """Stop a device and all its processes"""
    config = load_config()

    if device_index >= len(config['devices']):
        return jsonify({'success': False, 'error': 'Device not found'}), 404

    device = config['devices'][device_index]
    udid = device['udid']
    device_name = device['name']
    appium_port = device['appium_port']
    wda_port = device['wda_local_port']

    print(f"\n{'='*60}")
    print(f"Stopping {device_name} (UDID: {udid[:8]}...)")
    print(f"{'='*60}")

    # Stop tracked processes
    if udid in processes:
        proc_info = processes[udid]

        print("Stopping tracked bot...")
        stop_process(proc_info.get('bot'))

        # Close log file handle if it exists
        if 'bot_log_file' in proc_info and proc_info['bot_log_file']:
            try:
                proc_info['bot_log_file'].close()
                print("Closed bot log file")
            except:
                pass

        print("Stopping tracked Appium...")
        stop_process(proc_info.get('appium'))

        print("Stopping tracked WDA...")
        stop_process(proc_info.get('wda'))

        print("Stopping tracked iproxy...")
        stop_process(proc_info.get('iproxy'))

        # Remove by UDID
        del processes[udid]

    # Kill any orphaned processes by port/device-index
    print("Cleaning up any orphaned processes...")
    try:
        # Kill orphaned Appium on this port
        subprocess.run(f"lsof -ti:{appium_port} | xargs kill -9 2>/dev/null", shell=True)

        # Kill orphaned iproxy on this port
        subprocess.run(f"lsof -ti:{wda_port} | xargs kill -9 2>/dev/null", shell=True)

        # Kill orphaned run_device.py for this device index
        subprocess.run(f"pkill -f 'run_device.py --device-index {device_index}'", shell=True)

        # Kill orphaned xcodebuild for this UDID
        subprocess.run(f"pkill -f 'xcodebuild.*{udid}'", shell=True)

        print("Cleanup complete")
    except Exception as e:
        print(f"Cleanup error (non-fatal): {e}")

    print(f"✅ {device_name} stopped")
    print(f"{'='*60}\n")

    return jsonify({'success': True})


@app.route('/api/device/<int:device_index>/logs')
def get_device_logs(device_index):
    """Get filtered logs for a device (only creation process)"""
    config = load_config()

    if device_index >= len(config['devices']):
        return jsonify({'error': 'Device not found'}), 404

    device = config['devices'][device_index]
    log_file = f"{LOGS_DIR}/{device['name']}.log"

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()

            # Simple filter: Skip only Appium/Node.js stack traces, keep everything else
            filtered_lines = []

            for line in lines:
                # Skip empty lines
                if not line.strip():
                    continue

                # Skip Node.js stack trace lines (start with "    at ")
                if line.startswith('    at '):
                    continue

                # Skip lines with Node.js file paths
                if '/node_modules/' in line or '/opt/homebrew/' in line or '/.appium/' in line:
                    continue

                # Skip lines ending with .js: and a number (JavaScript file references)
                if '.js:' in line and any(c.isdigit() for c in line.split('.js:')[-1][:10]):
                    continue

                # Include everything else (run_device.py output)
                filtered_lines.append(line)

            # Get last 200 filtered lines
            filtered_logs = ''.join(filtered_lines[-200:])

            if not filtered_logs.strip():
                return jsonify({'logs': '⏳ Waiting for account creation activity...\n\nStart the device to see live account creation logs.'})

            return jsonify({'logs': filtered_logs})
    except FileNotFoundError:
        return jsonify({'logs': '📋 No logs yet.\n\nClick Start to begin account creation.'})
    except Exception as e:
        return jsonify({'logs': f'Error reading logs: {str(e)}'})


@app.route('/api/device/<int:device_index>/stats/update', methods=['POST'])
def update_device_stats(device_index):
    """Update stats for a device (called by the bot)"""
    data = request.json
    stat_type = data.get('type')  # 'successful', 'confirm_human', or 'failed'
    category = data.get('category')  # 'first_request', 'second_request', or 'multiple_numbers' (optional)

    if stat_type not in ['successful', 'confirm_human', 'failed']:
        return jsonify({'success': False, 'error': 'Invalid stat type'}), 400

    # Initialize stats for this device if not exists
    if device_index not in device_stats:
        device_stats[device_index] = {'successful': 0, 'confirm_human': 0, 'failed': 0}

    # Initialize detailed stats for this device if not exists
    if device_index not in detailed_stats:
        detailed_stats[device_index] = {
            'successful': {'first_request': 0, 'second_request': 0, 'multiple_numbers': 0},
            'confirm_human': {'first_request': 0, 'second_request': 0, 'multiple_numbers': 0}
        }

    # Increment the stat
    device_stats[device_index][stat_type] += 1

    # If category provided, update detailed stats (only for successful and confirm_human)
    if category and stat_type in ['successful', 'confirm_human']:
        if category in ['first_request', 'second_request', 'multiple_numbers']:
            detailed_stats[device_index][stat_type][category] += 1

    return jsonify({'success': True, 'stats': device_stats[device_index]})


@app.route('/api/device/<int:device_index>/stats', methods=['GET'])
def get_device_stats(device_index):
    """Get stats for a device"""
    stats = device_stats.get(device_index, {'successful': 0, 'confirm_human': 0, 'failed': 0})
    return jsonify(stats)


@app.route('/api/device/<int:device_index>/stats/detailed', methods=['GET'])
def get_device_detailed_stats(device_index):
    """Get detailed stats for a device"""
    detailed = detailed_stats.get(device_index, {
        'successful': {'first_request': 0, 'second_request': 0, 'multiple_numbers': 0},
        'confirm_human': {'first_request': 0, 'second_request': 0, 'multiple_numbers': 0}
    })
    return jsonify(detailed)


@app.route('/api/logs/cleanup', methods=['POST'])
def cleanup_logs():
    """Manually clean up large log files"""
    try:
        max_size_mb = request.json.get('max_size_mb', 100) if request.json else 100

        print(f"\n{'='*60}")
        print(f"Manual log cleanup requested (files > {max_size_mb}MB)")
        print(f"{'='*60}")

        cleanup_large_logs(max_size_mb=max_size_mb)

        print(f"{'='*60}\n")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """Shutdown all processes"""
    config = load_config()

    # Find device indices for all running UDIDs
    for udid in list(processes.keys()):
        # Find the device index for this UDID
        for idx, device in enumerate(config['devices']):
            if device['udid'] == udid:
                stop_device(idx)
                break

    return jsonify({'success': True})


def cleanup_all_processes():
    """Stop all running devices when dashboard shuts down"""
    global _cleanup_in_progress

    # Prevent multiple cleanup calls
    if _cleanup_in_progress:
        return

    _cleanup_in_progress = True

    # Log cleanup to file since terminal might be closed
    cleanup_log = os.path.join(LOGS_DIR, 'dashboard_cleanup.log')

    def log_cleanup(msg):
        """Log to both console and file"""
        print(msg)
        try:
            with open(cleanup_log, 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        except:
            pass

    log_cleanup("\n" + "="*60)
    log_cleanup("Dashboard shutting down - Stopping all devices...")
    log_cleanup("="*60)

    config = load_config()

    # Stop tracked processes
    if processes:
        for udid in list(processes.keys()):
            # Find device by UDID
            for idx, device in enumerate(config['devices']):
                if device['udid'] == udid:
                    log_cleanup(f"\nStopping {device['name']}...")
                    try:
                        stop_device(idx)
                    except Exception as e:
                        log_cleanup(f"Error stopping {device['name']}: {e}")
                    break

    # Also kill any orphaned processes by port (in case tracking failed)
    log_cleanup("\nKilling any remaining orphaned processes...")
    for device in config['devices']:
        try:
            appium_port = device['appium_port']
            wda_port = device['wda_local_port']
            udid = device['udid']

            # Kill all related processes
            subprocess.run(f"lsof -ti:{appium_port} | xargs kill -9 2>/dev/null", shell=True)
            subprocess.run(f"lsof -ti:{wda_port} | xargs kill -9 2>/dev/null", shell=True)
            subprocess.run(f"pkill -f 'run_device.py' 2>/dev/null", shell=True)
            subprocess.run(f"pkill -f 'xcodebuild.*{udid}' 2>/dev/null", shell=True)
        except:
            pass

    log_cleanup("\n" + "="*60)
    log_cleanup("All devices stopped. Dashboard shut down complete.")
    log_cleanup("="*60)


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    signal_names = {
        signal.SIGINT: 'SIGINT (Ctrl+C)',
        signal.SIGTERM: 'SIGTERM (Kill)',
        signal.SIGHUP: 'SIGHUP (Terminal closed)'
    }
    signal_name = signal_names.get(sig, f'Signal {sig}')
    print(f"\n\nReceived {signal_name}...")
    cleanup_all_processes()
    sys.exit(0)


if __name__ == '__main__':
    # Create necessary directories
    os.makedirs(LOGS_DIR, exist_ok=True)

    # Ensure config file exists
    if not os.path.exists(CONFIG_FILE):
        save_config({
            'devices': [],
            'shared_config': {
                'xcodeOrgId': '6K732U2AZU',
                'xcodeSigningId': 'iPhone Developer',
                'updatedWDABundleID': 'com.kevin.WebDriverAgentRunner',
                'platformName': 'iOS',
                'automationName': 'XCUITest',
                'newCommandTimeout': 1000,
                'showXcodeLog': True,
                'useNewWDA': True,
                'noReset': True
            }
        })

    # Register cleanup handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Kill command
    signal.signal(signal.SIGHUP, signal_handler)   # Terminal window closed
    atexit.register(cleanup_all_processes)         # Normal exit

    print("="*60)
    print("Instagram Bot Dashboard Starting...")
    print("="*60)

    # Ask user to choose IP rotation mode
    print("\nSelect IP rotation mode:")
    print("  1. Mobile Data (uses Shortcuts to toggle airplane mode)")
    print("  2. Potatso Proxies (switches between proxy servers)")
    print("")

    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            globals()['IP_ROTATION_MODE'] = "mobile_data"
            print("✓ Selected: Mobile Data mode")
            break
        elif choice == "2":
            globals()['IP_ROTATION_MODE'] = "potatso"
            print("✓ Selected: Potatso Proxies mode")
            break
        else:
            print("Invalid choice. Please enter 1 or 2.")

    print("")
    print("="*60)
    print("\nOpen in browser: http://localhost:5000")
    print("\n⚠️  IMPORTANT: Closing this dashboard will automatically stop")
    print("    ALL running devices (Ctrl+C or close terminal window)")
    print("    Cleanup logs: logs/dashboard_cleanup.log")
    print("="*60)

    try:
        # Use threaded=False to ensure cleanup runs properly
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\nReceived Ctrl+C, shutting down...")
        cleanup_all_processes()
        sys.exit(0)
