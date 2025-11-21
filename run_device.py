from appium import webdriver
from appium.options.ios import XCUITestOptions
import time
# TouchAction is deprecated in Appium 5.x - using W3C actions instead
from selenium.webdriver.common.by import By
from random import randrange
import names
import password_generator
import random
from datetime import datetime, timedelta
import sys
import requests
from faker import Faker
import string
import signal
import traceback
import os
import json
import argparse
import subprocess

# Default IP rotation mode (will be overridden by command line argument)
IP_ROTATION_MODE = 'potatso'

# Default phone number strategy (will be overridden by command line argument)
PHONE_NUMBER_STRATEGY = 'multiple'  # 'single' or 'multiple'

# Try to import psutil for memory monitoring (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Note: psutil not available - memory monitoring disabled")

DAISY_SMS_KEY = "wwAdNI6Ff56LGL9OIaiCqYSIoJdL72"
SMS_POOL_KEY = ""

fake = Faker()

# Global driver variable for WDA recovery
driver = None

# Global variables to track phone number attempts for detailed stats
phone_numbers_tried = 0
sms_requests_for_current_number = 0


# Signal handler to catch why script is being killed
def signal_handler(signum, frame):
    """Handle signals to debug why script is being killed"""
    signal_name = signal.Signals(signum).name
    print("\n" + "="*60)
    print(f"⚠️  SIGNAL RECEIVED: {signal_name} ({signum})")
    print("="*60)

    if signum == signal.SIGKILL:
        print("SIGKILL received - Process is being forcefully terminated!")
        print("This is usually caused by:")
        print("  1. Out of Memory (OOM killer)")
        print("  2. System resource limits")
        print("  3. Manual kill -9 command")
    elif signum == signal.SIGTERM:
        print("SIGTERM received - Graceful shutdown requested")
    elif signum == signal.SIGINT:
        print("SIGINT received - Ctrl+C pressed")

    # Print memory usage
    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        print(f"Current memory usage: {memory_mb:.1f} MB")
    except:
        pass

    # Print stack trace
    print("\nStack trace at time of signal:")
    traceback.print_stack(frame)
    print("="*60 + "\n")

    # Exit gracefully
    sys.exit(0)


# Register signal handlers (note: SIGKILL cannot be caught, but we try others)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
# SIGKILL (9) cannot be caught, but SIGTERM (15) can

# Periodic memory monitoring
def log_memory_usage():
    """Log current memory usage"""
    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        print(f"[Memory: {memory_mb:.1f} MB]")
    except:
        pass


def is_wda_crashed(error):
    """Check if an error is caused by WDA crash"""
    error_str = str(error).lower()
    return ("econnrefused" in error_str and "8100" in error_str) or \
           "could not proxy command" in error_str or \
           "connection refused" in error_str or \
           "session is either terminated" in error_str or \
           "nosuchdrivererror" in error_str or \
           "invalidsessionidexception" in error_str


def restart_driver_session(options, device_config):
    """Restart the Appium driver session after WDA crash"""
    global driver

    print("\n" + "="*60)
    print("⚠️  WDA CRASH DETECTED - Restarting driver session...")
    print("="*60)

    udid = device_config['udid']
    device_name = device_config['name']
    wda_port = device_config['wda_local_port']
    appium_port = device_config['appium_port']
    appium_url = f"http://localhost:{appium_port}/wd/hub"

    # Try to quit existing session
    try:
        if driver:
            driver.quit()
            print("✓ Closed old driver session")
    except:
        print("Old session already closed")

    # Kill the xcodebuild process for this device (NOT iproxy - we need it to keep running)
    # iproxy forwards localhost:wda_port to device:8100, so we must keep it alive
    print(f"Killing xcodebuild process for device {udid}...")
    try:
        subprocess.run(f"pkill -9 -f 'xcodebuild.*{udid}'", shell=True)
        print("✓ Killed xcodebuild process")
    except:
        pass

    # Wait for cleanup
    print("Waiting 3 seconds for cleanup...")
    time.sleep(3)

    # Check if iproxy is still running on the port (it should be)
    print(f"Checking if iproxy is still running on port {wda_port}...")
    try:
        result = subprocess.run(f"lsof -ti:{wda_port}", shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print(f"✓ iproxy still running (PID: {result.stdout.strip()})")
        else:
            # iproxy is not running, need to restart it
            print("⚠️  iproxy not running, restarting...")
            iproxy_process = subprocess.Popen(
                ["iproxy", str(wda_port), "8100", "-u", udid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"✓ Started iproxy (PID: {iproxy_process.pid})")
            time.sleep(1)
    except Exception as e:
        print(f"Error checking/starting iproxy: {e}")

    # Start WDA using xcodebuild
    print(f"Starting WDA for {device_name}...")
    wda_dir = '/Users/kevinpencu/Downloads/WebDriverAgent'
    derived_data = f"/tmp/wda-{udid}"
    logs_dir = '/Users/kevinpencu/PycharmProjects/IG Creation Bot/logs'

    os.makedirs(logs_dir, exist_ok=True)
    wda_log_file = open(f"{logs_dir}/wda_{device_name}_restart.log", "w")

    try:
        wda_process = subprocess.Popen(
            [
                "xcodebuild",
                "-project", f"{wda_dir}/WebDriverAgent.xcodeproj",
                "-scheme", "WebDriverAgentRunner",
                "-configuration", "Debug",
                "-destination", f"id={udid}",
                "-derivedDataPath", derived_data,
                "-allowProvisioningUpdates",
                "test"
            ],
            stdout=wda_log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=wda_dir
        )
        print(f"✓ Started WDA xcodebuild (PID: {wda_process.pid})")
    except Exception as e:
        print(f"❌ Failed to start WDA: {e}")
        raise Exception("Could not start WDA after crash")

    # Wait for WDA to be ready
    print(f"Waiting for WDA to be ready on port {wda_port}...")
    wda_url = f"http://127.0.0.1:{wda_port}/status"
    wda_ready = False
    timeout = 90

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(wda_url, timeout=2)
            if response.status_code == 200:
                print(f"✓ WDA ready on port {wda_port}")
                wda_ready = True
                break
        except:
            pass
        elapsed = int(time.time() - start_time)
        if elapsed % 10 == 0 and elapsed > 0:
            print(f"  Still waiting for WDA... ({elapsed}s)")
        time.sleep(2)

    if not wda_ready:
        print(f"❌ WDA failed to start after {timeout} seconds")
        raise Exception("WDA timeout after crash recovery")

    # Reconnect to Appium
    print(f"Reconnecting to Appium at {appium_url}...")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Reconnection attempt {attempt + 1}/{max_retries}...")
            driver = webdriver.Remote(appium_url, options=options)
            print("✓ Successfully reconnected to Appium!")
            print("="*60 + "\n")
            return driver
        except Exception as e:
            print(f"Reconnection failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 5
                print(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                print("❌ Failed to reconnect after all attempts")
                raise Exception("Could not restart driver session after WDA crash")


def check_wda_health():
    """Quick health check to see if WDA is responsive"""
    global driver
    if not driver:
        return False

    try:
        driver.get_window_size()  # Simple command to test WDA
        return True
    except Exception as e:
        return not is_wda_crashed(e)


def execute_with_wda_recovery(func, options, *args, **kwargs):
    """Execute a function with automatic WDA crash recovery"""
    max_attempts = 3

    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if is_wda_crashed(e):
                print(f"WDA crash detected during {func.__name__} (attempt {attempt + 1}/{max_attempts})")
                if attempt < max_attempts - 1:
                    restart_driver_session(options, device_config)
                    time.sleep(2)  # Brief pause after restart
                else:
                    print(f"❌ Failed to execute {func.__name__} after {max_attempts} WDA recovery attempts")
                    raise
            else:
                # Not a WDA crash, re-raise the error
                raise


def get_random_username_from_file():
    """
    Get a random username from usernames.txt
    Deletes the username from the file immediately after selecting it
    Returns username or None if file is empty
    """
    usernames_file = "usernames.txt"

    try:
        # Read all usernames
        with open(usernames_file, 'r', encoding='utf-8') as f:
            usernames = [line.strip() for line in f.readlines() if line.strip()]

        if len(usernames) == 0:
            print("❌ usernames.txt is empty!")
            return None

        # Pick random username
        selected_username = random.choice(usernames)
        print(f"Selected username from file: {selected_username}")

        # Remove the selected username from list
        usernames.remove(selected_username)

        # Write back to file (overwrite)
        with open(usernames_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(usernames) + '\n' if usernames else '')

        print(f"✓ Deleted '{selected_username}' from usernames.txt ({len(usernames)} remaining)")

        return selected_username

    except FileNotFoundError:
        print("❌ usernames.txt not found! Please create this file with usernames.")
        return None
    except Exception as e:
        print(f"Error reading usernames.txt: {e}")
        return None


def delete_username_from_file(username):
    """
    Thread-safe function to delete a username from usernames.txt
    Used when Instagram says username already exists
    """
    import fcntl

    usernames_file = "usernames.txt"

    try:
        with open(usernames_file, 'r+', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                usernames = [line.strip() for line in f.readlines() if line.strip()]

                if username in usernames:
                    usernames.remove(username)

                    f.seek(0)
                    f.truncate()
                    f.write('\n'.join(usernames) + '\n' if usernames else '')
                    f.flush()

                    print(f"✓ Deleted '{username}' from usernames.txt (already exists on Instagram)")

            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        print(f"Error deleting username from file: {e}")


def buyNumber(provider, api_key):
    if provider == "daisy":
        try:
            buy_sms = f"https://daisysms.com/stubs/handler_api.php?api_key={api_key}&action=getNumber&service=ig&max_price=1.5"
            response_text = requests.get(buy_sms).text
            print(f"DaisySMS Response: {response_text}")

            if "ACCESS_NUMBER" in response_text:
                # Response format: ACCESS_NUMBER:rental_id:phone_number
                response = response_text.split(":")
                return f"{response[1]}:{response[2]}"
            elif "MAX_PRICE_EXCEEDED" in response_text:
                print("Max price exceeded. Increase max_price parameter.")
                return None
            elif "NO_NUMBERS" in response_text:
                print("No numbers available for Instagram at this time.")
                return None
            else:
                print(f"Unknown response from DaisySMS: {response_text}")
                return None
        except Exception as e:
            print(f"Error buying number: {str(e)}")
            return None


def human_like_typing(element, text, min_delay=0.02, max_delay=0.08):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))
        if random.random() < 0.03:  # 3% chance of a longer pause (reduced from 5%)
            time.sleep(random.uniform(0.1, 0.3))  # Shorter pauses


def simulate_backspace(element, num_chars=1):
    for _ in range(num_chars):
        element.send_keys('\b')
        time.sleep(random.uniform(0.02, 0.08))  # Faster backspacing


def password_old(accpw):
    try:
        password_field = driver.find_element(By.XPATH, '//*[@label="Password"]')
        password_field.click()
        random_delay(0.5, 1.5)

        # Simulate typing with occasional mistakes
        for i, char in enumerate(accpw):
            if random.random() < 0.1 and i > 0:  # 10% chance of making a mistake, but not on the first character
                wrong_char = chr(ord(char) + random.randint(1, 3))  # Type a nearby character
                human_like_typing(password_field, wrong_char)
                random_delay(0.1, 0.2)
                simulate_backspace(password_field)
                random_delay(0.1, 0.2)

            human_like_typing(password_field, char)

        random_delay(1, 2)
        driver.find_element(By.XPATH, '//*[@label="Next"]').click()
        print("Password entered and Next clicked")
        return True
    except Exception as e:
        print(f"Error in password step: {str(e)}")
        return False


def random_delay(min_seconds=0.5, max_seconds=2):
    time.sleep(random.uniform(min_seconds, max_seconds))


def cancelNumber(orderid, provider, api_key):
    """Cancel a phone number order"""
    if provider == "daisy":
        try:
            cancel_url = f"https://daisysms.com/stubs/handler_api.php?api_key={api_key}&action=setStatus&id={orderid}&status=-1"
            response = requests.get(cancel_url).text
            print(f"Cancelled number {orderid}: {response}")
            return True
        except Exception as e:
            print(f"Error cancelling number: {e}")
            return False


def checkNumber(orderid, provider, api_key):
    if provider == "daisy":
        import time as time_module
        start_time = time_module.time()
        max_wait_time = 30  # Hard coded to exactly 30 seconds

        attempt = 0
        while (time_module.time() - start_time) < max_wait_time:
            attempt += 1
            elapsed = int(time_module.time() - start_time)
            try:
                buy_sms = f"https://daisysms.com/stubs/handler_api.php?api_key={api_key}&action=getStatus&id={orderid}"
                response = requests.get(buy_sms).text
                print(f"[{elapsed}s] {response}")
                if "STATUS_OK" in response:
                    print(f"Code received after {elapsed} seconds!")
                    return response.split(":")[1]
                time_module.sleep(1)
            except Exception as e:
                print(f"Error checking SMS status at {elapsed}s: {e}")
                time_module.sleep(1)

        print(f"No code received after exactly 30 seconds, giving up on this attempt")
        return False


def rotateIP():
    print("Rotating IP...")
    try:
        # Press home button first to ensure we're on home screen
        print("Going to home screen...")
        driver.execute_script("mobile: pressButton", {"name": "home"})
        time.sleep(2)  # Wait for home screen to fully load

        # Check which IP rotation mode to use
        if IP_ROTATION_MODE == "mobile_data":
            # Mobile data mode: Use Shortcuts app to toggle airplane mode
            print("Using Mobile Data mode - toggling airplane mode via Shortcuts...")

            # Open Shortcuts app
            print("Looking for Shortcuts app on home screen...")
            shortcuts_found = False
            for attempt in range(3):
                try:
                    driver.find_element(By.XPATH, '//*[@label="Shortcuts"]').click()
                    shortcuts_found = True
                    break
                except:
                    if attempt < 2:
                        print(f"Shortcuts not found (attempt {attempt + 1}/3), pressing home and waiting...")
                        driver.execute_script("mobile: pressButton", {"name": "home"})
                        time.sleep(2)

            if not shortcuts_found:
                print("⚠️  Could not find Shortcuts app after 3 attempts")
                return

            time.sleep(1)
            print("Shortcuts app opened")

            # Click on the IP shortcut
            print("Looking for 'IP' shortcut...")
            ip_shortcut_found = False
            for attempt in range(5):
                try:
                    ip_shortcut = driver.find_element(By.XPATH, '//*[@label="IP"]')
                    ip_shortcut.click()
                    ip_shortcut_found = True
                    print("Clicked 'IP' shortcut")
                    break
                except:
                    if attempt < 4:
                        print(f"IP shortcut not found (attempt {attempt + 1}/5), waiting...")
                        time.sleep(1)

            if not ip_shortcut_found:
                print("⚠️  Could not find IP shortcut")
                return

            # Wait for airplane mode toggle to complete (3 sec on + 3 sec off + buffer)
            print("Waiting 5 seconds for airplane mode toggle to complete...")
            time.sleep(5)

            print("IP rotated via airplane mode toggle!")
            # Stay in Shortcuts app - crane() will click IG shortcut from here
            return

        # Potatso mode (default)
        # Open Potatso by clicking on the app icon from home screen
        print("Looking for Potatso app on home screen...")
        potatso_found = False
        for attempt in range(3):
            try:
                driver.find_element(By.XPATH, '//*[@label="Potatso"]').click()
                potatso_found = True
                break
            except:
                if attempt < 2:
                    print(f"Potatso not found (attempt {attempt + 1}/3), pressing home and waiting...")
                    driver.execute_script("mobile: pressButton", {"name": "home"})
                    time.sleep(2)

        if not potatso_found:
            print("⚠️  Could not find Potatso app after 3 attempts")
            return

        time.sleep(1)
        print("Potatso app opened")

        # Find all proxy cells on the "Choose Proxy" screen
        try:
            all_cells = driver.find_elements(By.XPATH, '//XCUIElementTypeCell')
            print(f"Found {len(all_cells)} proxy cells")

            if len(all_cells) >= 2:
                # Find which cell is currently selected by looking for "BackgroundSelected" in children
                selected_index = -1

                for i, cell in enumerate(all_cells):
                    try:
                        # Look for child element with name="BackgroundSelected"
                        children = cell.find_elements(By.XPATH, './/*')
                        for child in children:
                            child_name = child.get_attribute("name")
                            if child_name == "BackgroundSelected":
                                selected_index = i
                                print(f"Currently selected proxy is at index {i} (found BackgroundSelected)")
                                break
                        if selected_index != -1:
                            break
                    except:
                        pass

                # If still not found, assume index 0
                if selected_index == -1:
                    print("Could not detect selected proxy, assuming index 0")
                    selected_index = 0

                # Calculate next proxy index (wrap around to 0 if at end)
                next_index = (selected_index + 1) % len(all_cells)

                print(f"Switching from proxy {selected_index} to proxy {next_index}")
                all_cells[next_index].click()
                print(f"Switched to proxy at index {next_index}")
                time.sleep(0.3)  # Reduced from 1
            elif len(all_cells) == 1:
                # Only one proxy, click it anyway
                all_cells[0].click()
                print("Only one proxy available, clicked it")
                time.sleep(0.3)  # Reduced from 1
        except Exception as e:
            print(f"Error finding cells: {e}")
            # Try alternative: find by label text
            try:
                proxies = driver.find_elements(By.XPATH, '//*[contains(@label, "proxylab") or contains(@label, "HTTP")]')
                if len(proxies) > 1:
                    proxies[1].click()
                    print("Switched proxy using label method")
                    time.sleep(0.3)  # Reduced from 1
            except:
                print("Could not switch proxy")

        print("IP rotated!")
        # Return to home screen
        driver.execute_script("mobile: pressButton", {"name": "home"})
        time.sleep(0.5)  # Reduced from 1
    except Exception as e:
        print(f"Error rotating IP: {e}")
        # Try to return to home screen anyway
        try:
            driver.execute_script("mobile: pressButton", {"name": "home"})
        except:
            pass


def get_next_container_number(udid):
    """Get the next container number for a specific device UDID"""
    container_tracking_file = "container_tracking.json"

    # Load existing tracking data
    try:
        with open(container_tracking_file, 'r') as f:
            tracking_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        tracking_data = {}

    # Get current container number for this device (default to 0 if not found)
    current_number = tracking_data.get(udid, 0)

    # Increment for next container
    next_number = current_number + 1

    # Save updated number
    tracking_data[udid] = next_number
    with open(container_tracking_file, 'w') as f:
        json.dump(tracking_data, f, indent=2)

    print(f"Container number for device {udid[:8]}: {next_number}")
    return next_number


def crane():
    """Rotate IP and create new Instagram container using combined iOS Shortcut"""
    print("Rotating IP and creating new container using combined Shortcut...")

    try:
        # Always go to home and open Shortcuts to be safe
        driver.execute_script("mobile: pressButton", {"name": "home"})
        time.sleep(1)
        print("Returned to home screen")

        # Open Shortcuts app
        print("Opening Shortcuts app...")
        try:
            shortcuts_app = driver.find_element(By.XPATH, '//*[@label="Shortcuts"]')
            shortcuts_app.click()
            time.sleep(2)
            print("Shortcuts app opened")
        except Exception as e:
            print(f"Error opening Shortcuts app: {e}")
            # Try alternative method - activate app by bundle ID
            try:
                driver.activate_app("com.apple.shortcuts")
                time.sleep(2)
                print("Shortcuts app activated via bundle ID")
            except Exception as e2:
                print(f"Failed to open Shortcuts: {e2}")
                return

        # Click on "IG" shortcut
        print("Looking for 'IG' shortcut...")
        max_attempts = 5
        ig_clicked = False

        for attempt in range(max_attempts):
            try:
                ig_shortcut = driver.find_element(By.XPATH, '//*[@label="IG"]')
                ig_shortcut.click()
                print("Clicked on 'IG' shortcut (combined IP rotation + container)")
                ig_clicked = True
                break
            except:
                print(f"'IG' shortcut not found (attempt {attempt + 1}/{max_attempts}), waiting...")
                time.sleep(1)

        if not ig_clicked:
            print("Failed to find 'IG' shortcut")
            driver.execute_script("mobile: pressButton", {"name": "home"})
            return

        # Wait for IP rotation (airplane mode on/off) and container name popup to appear
        print("Waiting for IP rotation (airplane mode toggle) and container name popup...")

        # Get next container number for this device
        container_number = get_next_container_number(device_config['udid'])

        # Actively search for text input field (wait as long as needed - no timeout)
        print("Scanning for container name popup...")
        text_field = None
        attempt = 0
        while text_field is None:
            attempt += 1
            try:
                text_field = driver.find_element(By.XPATH, '//XCUIElementTypeTextField')
                print(f"✓ Container name popup found after {attempt} attempt(s)")
            except:
                if attempt % 5 == 0:  # Print status every 5 seconds
                    print(f"Still waiting for container popup... ({attempt}s)")
                time.sleep(1)

        # Enter container number
        try:
            text_field.click()
            time.sleep(0.5)
            text_field.send_keys(str(container_number))
            print(f"Entered container name: {container_number}")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error entering container name: {e}")
            print("Container creation failed - retrying...")
            driver.execute_script("mobile: pressButton", {"name": "home"})
            time.sleep(2)
            return crane()  # Retry the entire process

        # Click "Done" button (wait for it if needed)
        print("Looking for 'Done' button...")
        done_clicked = False
        done_attempt = 0
        while not done_clicked and done_attempt < 30:  # Max 30 seconds
            done_attempt += 1
            try:
                done_button = driver.find_element(By.XPATH, '//*[@label="Done"]')
                done_button.click()
                print("Clicked 'Done' button")
                done_clicked = True
            except:
                if done_attempt % 5 == 0:
                    print(f"Still waiting for 'Done' button... ({done_attempt}s)")
                time.sleep(1)

        if not done_clicked:
            print("Failed to find 'Done' button after 30 seconds - retrying container creation")
            driver.execute_script("mobile: pressButton", {"name": "home"})
            time.sleep(2)
            return crane()  # Retry the entire process

        time.sleep(3)  # Wait for shortcut to complete
        print("Container creation completed")

        # Return to home screen
        driver.execute_script("mobile: pressButton", {"name": "home"})
        time.sleep(1)
        print("Returned to home screen")

        print("✓ IP rotation and container reset completed successfully using combined Shortcut!")

    except Exception as e:
        print(f"Error during container reset: {e}")
        # Try to return to home screen
        try:
            driver.execute_script("mobile: pressButton", {"name": "home"})
        except:
            pass


def click_didnt_get_code_button(log_coordinates=False):
    """
    Find and click the 'I didn't get the code' button.
    Returns True if successful, False otherwise.
    If log_coordinates=True, logs all button coordinates for debugging.
    """
    if log_coordinates:
        print("\n=== LOGGING ALL BUTTON COORDINATES ===")
        try:
            all_buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
            for i, btn in enumerate(all_buttons):
                try:
                    loc = btn.location
                    label = btn.get_attribute('label')
                    print(f"Button {i}: position ({loc['x']}, {loc['y']}), label: '{label}'")
                except:
                    pass
        except:
            pass
        print("=== END COORDINATE LOG ===\n")

    # Strategy 1: Try to find button by label text (including "Try another way")
    try:
        button = driver.find_element(By.XPATH, '//*[@label="I didn\'t get the code" or @label="I didn\'t get the code." or @label="Try another way" or contains(@label, "didn\'t get") or contains(@label, "another way")]')
        location = button.location
        label = button.get_attribute('label')
        print(f"✓ Found button by label at position ({location['x']}, {location['y']}): '{label}'")
        button.click()
        print(f"Clicked '{label}' button (found by label)")
        return True
    except:
        print("Button not found by label, trying other methods...")

    # Strategy 2: Look for button by coordinates (original method, but with wider tolerance)
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
        print(f"Found {len(buttons)} total buttons on screen")
        for button in buttons:
            try:
                location = button.location
                label = button.get_attribute('label')
                # Check if coordinates are in the expected area (left side, middle-lower of screen)
                # Increased tolerance and expanded search area
                if location['x'] < 100 and 200 < location['y'] < 500:
                    # Check if label contains relevant text (including "Try another way")
                    if label and ('code' in label.lower() or 'didn' in label.lower() or 'another' in label.lower() or 'way' in label.lower()):
                        print(f"✓ Found button by coordinates at ({location['x']}, {location['y']}) with label: '{label}'")
                        button.click()
                        print(f"Clicked '{label}' button (found at position {location['x']}, {location['y']})")
                        return True
            except:
                continue
    except Exception as e:
        print(f"Error in coordinate-based search: {e}")

    # Strategy 3: Look for any button with text containing "code", "another", or "way" on the left side
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
        for button in buttons:
            try:
                label = button.get_attribute('label')
                location = button.location
                if label and location['x'] < 150:
                    label_lower = label.lower()
                    if 'code' in label_lower or 'another' in label_lower or 'way' in label_lower:
                        print(f"✓ Found button with relevant text at ({location['x']}, {location['y']}): '{label}'")
                        button.click()
                        print(f"Clicked button: {label}")
                        return True
            except:
                continue
    except:
        pass

    # Strategy 4: Look for ANY button on the left side of screen (broader search)
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
        print(f"Strategy 4: Checking all {len(buttons)} buttons on left side...")
        for button in buttons:
            try:
                location = button.location
                label = button.get_attribute('label')
                # Any button on the left side below the top navbar
                if location['x'] < 100 and location['y'] > 100:
                    print(f"  - Button at ({location['x']}, {location['y']}), label: '{label}'")
            except:
                continue
    except:
        pass

    print("'I didn't get the code' button not found after trying all strategies")
    return False


def click_back_arrow():
    """
    Click the back arrow button (top left of screen).
    Returns True if successful, False otherwise.
    """
    # Try multiple approaches to find the back button

    # Strategy 1: Try common back button labels
    back_labels = ["Back", "back", "←", "Back Button", "Navigate up"]
    for label in back_labels:
        try:
            back_button = driver.find_element(By.XPATH, f'//*[@label="{label}"]')
            back_button.click()
            print(f"Clicked back arrow using label: {label}")
            return True
        except:
            continue

    # Strategy 2: Find all buttons and click the first one in top-left position
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
        for button in buttons:
            try:
                location = button.location
                size = button.size
                # More accurate top-left detection: x < 80 and y < 200
                if location['x'] < 80 and location['y'] < 200:
                    button.click()
                    print(f"Clicked back arrow at position ({location['x']}, {location['y']})")
                    return True
            except:
                continue
    except:
        pass

    # Strategy 3: Try finding by accessibility id
    try:
        back_button = driver.find_element(By.XPATH, '//*[@accessibilityIdentifier="back" or @accessibilityIdentifier="Back"]')
        back_button.click()
        print("Clicked back arrow using accessibility identifier")
        return True
    except:
        pass

    # Strategy 4: Look for button with empty label in top-left (back arrows often have no text)
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton[@label="" or not(@label)]')
        for button in buttons:
            try:
                location = button.location
                if location['x'] < 80 and location['y'] < 200:
                    button.click()
                    print(f"Clicked unlabeled back arrow at position ({location['x']}, {location['y']})")
                    return True
            except:
                continue
    except:
        pass

    print("Back arrow button not found")
    return False


def check_login_popup():
    try:
        login_popup = driver.find_element(By.XPATH, '//*[contains(@label, "Are you trying to log in?")]')
        if login_popup.is_displayed():
            print("'Are you trying to log in?' popup detected. Number already associated with account.")
            # Click "Create new account" button to create new account with new password
            try:
                create_new_button = driver.find_element(By.XPATH, '//*[@label="Create new account"]')
                create_new_button.click()
                print("Clicked 'Create new account' on login popup")
                return "continue_with_wait"  # Signal that we need to wait for page load
            except Exception as e:
                print(f"Failed to click 'Create new account': {e}")
                return "restart"
    except:
        pass
    return "continue"


def mobileNumber(key):
    global phone_numbers_tried, sms_requests_for_current_number
    is_retry = False  # Track if we're retrying after a failed number

    while True:
        # Increment phone number counter (each iteration tries a new number)
        phone_numbers_tried += 1
        sms_requests_for_current_number = 1  # Reset to 1 for each new number
        try:
            # Find mobile number field - try both possible labels
            mobile_field = None
            try:
                mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
            except:
                print("Mobile number field not found, waiting...")
                time.sleep(2)
                continue

            if mobile_field and mobile_field.is_enabled():
                print("Buying number")
                buy = buyNumber("daisy", key)
                print(f"Received from Daisy: {buy}")
                if buy is None:
                    print("Failed to buy number. Retrying...")
                    continue

                orderid, number = buy.split(":")
                print(f"Order ID: {orderid}, Phone Number: {number}")

                # Only clear if we're retrying (previous number failed)
                if is_retry:
                    print("Clearing old phone number from field (retry after failed code)...")
                    # Click field to focus it
                    mobile_field.click()
                    time.sleep(0.3)
                    # Send 14 backspaces very fast to clear the old number
                    print("Sending 14 backspaces to clear field...")
                    for _ in range(14):
                        mobile_field.send_keys('\b')  # Send backspace very fast (no delay)
                    print("✓ Field cleared with backspaces")
                else:
                    print("First attempt - field should be empty")
                    # Click field to focus it
                    mobile_field.click()
                    time.sleep(0.3)

                print("Entering new number with +1 prefix...")
                mobile_field.send_keys("+1" + number)  # Always use +1 (US) prefix
                print(f"Entered phone number: +1{number}")

                # Verify the correct number was entered
                time.sleep(0.5)
                final_value = mobile_field.get_attribute('value')
                print(f"Field now contains: '{final_value}'")

                random_delay(1, 3)  # Longer delay after entering the number

                # Try clicking Next up to 2 times (in case first click doesn't register)
                next_click_attempts = 2
                for next_attempt in range(next_click_attempts):
                    next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                    if next_button.is_enabled():
                        next_button.click()
                        print(f"Clicked Next after entering phone number (attempt {next_attempt + 1}/{next_click_attempts})")
                    else:
                        print("Next button not enabled after entering phone number")
                        return False

                    # Wait and check if we reach confirmation screen or see a popup
                    print("Waiting to see if we reach confirmation screen or see a popup...")
                    progress_detected = False
                    for wait_check in range(10):  # Check for 10 seconds
                        time.sleep(1)

                        # Check for "incorrect number" error (means old number wasn't cleared)
                        try:
                            error_msg = driver.find_element(By.XPATH, '//*[contains(@label, "may be incorrect")]')
                            if error_msg.is_displayed():
                                print("⚠️  'Number may be incorrect' error - previous number wasn't cleared properly!")
                                # Clear the field completely and retry with same number
                                mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
                                mobile_field.clear()
                                time.sleep(0.3)
                                print("Cleared field, re-typing number...")
                                mobile_field.send_keys("+1" + number)
                                print(f"Re-entered phone number: +1{number}")
                                time.sleep(1)
                                # Click Next again
                                next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                                next_button.click()
                                print("Clicked Next again after clearing error")
                                # Reset wait_check to start checking from beginning
                                continue
                        except:
                            pass

                        # Check if confirmation code screen appeared
                        try:
                            driver.find_element(By.XPATH, '//*[contains(@label, "Enter the confirmation code") or contains(@label, "Confirmation code")]')
                            print(f"✓ Confirmation code screen appeared after {wait_check + 1} seconds")
                            progress_detected = True
                            break
                        except:
                            pass

                        # Check if "Are you trying to log in?" popup appeared
                        try:
                            driver.find_element(By.XPATH, '//*[contains(@label, "Are you trying to log in?")]')
                            print(f"✓ Login popup appeared after {wait_check + 1} seconds")
                            progress_detected = True
                            break
                        except:
                            pass

                        # Check if "Make sure your device is nearby" popup appeared
                        try:
                            driver.find_element(By.XPATH, '//*[contains(@label, "Make sure") and contains(@label, "device")]')
                            print(f"✓ Device nearby popup appeared after {wait_check + 1} seconds")
                            progress_detected = True
                            break
                        except:
                            pass

                        # Check if Continue button appeared (from device nearby popup)
                        try:
                            continue_button = driver.find_element(By.XPATH, '//*[@label="Continue"]')
                            edit_button = driver.find_element(By.XPATH, '//*[@label="Edit number"]')
                            if continue_button.is_displayed() and edit_button.is_displayed():
                                print(f"✓ Device nearby popup detected via buttons after {wait_check + 1} seconds")
                                progress_detected = True
                                break
                        except:
                            pass

                        # If at 10 seconds, check if still on mobile number screen
                        if wait_check == 9:
                            try:
                                driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
                                print(f"Still on mobile number screen after 10 seconds (attempt {next_attempt + 1})")

                                # Check for "Something went wrong" error - means account creation failed
                                try:
                                    something_wrong = driver.find_element(By.XPATH, '//*[contains(@label, "Something went wrong")]')
                                    if something_wrong:
                                        print("❌ 'Something went wrong. Please try again later.' error detected!")
                                        print("Account creation failed - restarting process...")
                                        return "restart"
                                except:
                                    pass

                                progress_detected = False
                            except:
                                # Field not found, assume we moved somewhere
                                print(f"Mobile field not found after 10 seconds - moved to different screen")
                                progress_detected = True

                    if progress_detected:
                        # We detected progress (popup or confirmation screen)
                        print("Progress detected, continuing...")
                        break
                    elif next_attempt < next_click_attempts - 1:
                        # No progress - try clicking Next again
                        print("No progress detected, retrying Next button click...")
                    else:
                        # Final attempt - continue anyway
                        print("No clear progress after all Next attempts, continuing with flow...")

                # Additional wait for any loading to finish
                print("Waiting for Instagram to finish loading...")
                time.sleep(2)

                # Wait for Loading button to disappear (max 10 seconds)
                for _ in range(10):
                    try:
                        loading = driver.find_element(By.XPATH, '//*[@label="Loading"]')
                        if loading.is_displayed():
                            print("Still loading...")
                            time.sleep(1)
                        else:
                            break
                    except:
                        # Loading button gone, good to proceed
                        break

                random_delay(1, 2)

                # Check for "Make sure your device is nearby" popup
                print("Checking for 'device nearby' popup...")
                popup_handled = False

                # Try multiple ways to detect the popup
                try:
                    # Method 1: Look for the popup text
                    device_nearby_popup = driver.find_element(By.XPATH, '//*[contains(@label, "Make sure") and contains(@label, "device")]')
                    if device_nearby_popup.is_displayed():
                        print("'Make sure your device is nearby' popup detected (Method 1)")
                        popup_handled = True
                except Exception as e:
                    print(f"Method 1 failed: {e}")

                # Method 2: Look for Continue button + Edit number button (unique to this popup)
                if not popup_handled:
                    try:
                        continue_button = driver.find_element(By.XPATH, '//*[@label="Continue"]')
                        edit_button = driver.find_element(By.XPATH, '//*[@label="Edit number"]')
                        if continue_button.is_displayed() and edit_button.is_displayed():
                            print("'Device nearby' popup detected via buttons (Method 2)")
                            popup_handled = True
                    except Exception as e:
                        print(f"Method 2 failed: {e}")

                # If popup detected by either method, click Continue
                if popup_handled:
                    try:
                        continue_button = driver.find_element(By.XPATH, '//*[@label="Continue"]')
                        continue_button.click()
                        print("✓ Clicked 'Continue' on device nearby popup")
                        random_delay(2, 3)
                    except Exception as e:
                        print(f"Failed to click Continue: {e}")
                else:
                    print("No 'device nearby' popup found, continuing...")

                # Check for "Are you trying to log in?" popup
                popup_result = check_login_popup()
                if popup_result == "restart":
                    continue  # Will retry with same number
                elif popup_result == "continue_with_wait":
                    # Popup was handled, need to wait for confirmation code screen
                    print("Waiting for confirmation code screen after popup...")
                    time.sleep(5)  # Wait for page transition

                # Check for "Create new account" button, indicating we're back at the start
                try:
                    driver.find_element(By.XPATH, '//*[@label="Create new account"]')
                    print("'Create new account' button found. Number likely already in use.")

                    if PHONE_NUMBER_STRATEGY == 'single':
                        print("Single number strategy enabled - restarting account creation")
                        return False  # Restart entire account creation

                    is_retry = True
                    continue  # Retry with new number
                except:
                    pass  # If not found, continue with the normal flow

                # Now wait and check for confirmation code screen
                print("Looking for confirmation code screen...")
                conf_field_found = False
                for attempt in range(10):  # Try for up to 10 seconds
                    try:
                        # Try multiple ways to detect the confirmation code screen
                        conf_title = driver.find_element(By.XPATH, '//*[contains(@label, "Enter the confirmation code") or contains(@label, "Confirmation code")]')
                        if conf_title:
                            print("Confirmation code screen found, waiting for SMS...")
                            conf_field_found = True
                            break
                    except:
                        pass

                    # Alternative: look for the 6 input boxes or the text field
                    try:
                        # Look for any text field on the confirmation screen
                        text_fields = driver.find_elements(By.XPATH, '//XCUIElementTypeTextField')
                        if len(text_fields) > 0:
                            print(f"Found {len(text_fields)} text fields on confirmation screen")
                            conf_field_found = True
                            break
                    except:
                        pass

                    print(f"Confirmation code screen not found yet (attempt {attempt + 1}/10)...")
                    time.sleep(1)

                if not conf_field_found:
                    print("Could not find confirmation code screen after waiting.")

                    if PHONE_NUMBER_STRATEGY == 'single':
                        print("Single number strategy enabled - restarting account creation")
                        return False  # Restart entire account creation

                    print("Multiple number strategy - retrying with new number...")
                    is_retry = True
                    continue

                # Check if Instagram sent code to WhatsApp instead of SMS
                print("Checking if code was sent to WhatsApp instead of SMS...")
                try:
                    whatsapp_element = driver.find_element(By.XPATH, '//*[contains(@label, "WhatsApp") or contains(@value, "WhatsApp")]')
                    if whatsapp_element:
                        print("WARNING: Code was sent to WhatsApp! Requesting SMS instead...")
                        # Scroll down to find "I didn't get the code" button using screen swipe
                        print("Scrolling down using screen swipe...")
                        try:
                            # Get screen dimensions
                            screen_size = driver.get_window_size()
                            # Swipe up from bottom to scroll down
                            driver.execute_script("mobile: dragFromToForDuration", {
                                "fromX": screen_size['width'] / 2,
                                "fromY": screen_size['height'] * 0.8,
                                "toX": screen_size['width'] / 2,
                                "toY": screen_size['height'] * 0.2,
                                "duration": 0.5
                            })
                            print("Scroll swipe completed")
                            time.sleep(1)
                        except Exception as scroll_err:
                            if is_wda_crashed(scroll_err):
                                print("⚠️  WDA CRASH detected during WhatsApp scroll!")
                                return "restart"
                            print(f"Scroll failed: {scroll_err}, continuing anyway...")

                        # Tap directly on the "I didn't get the code" button at hardcoded coordinates
                        print("Tapping 'I didn't get the code' button at hardcoded position (16, 338)...")
                        try:
                            driver.execute_script("mobile: tap", {"x": 16, "y": 338})
                            print("✓ Tapped 'I didn't get the code' button successfully")
                            time.sleep(2)
                        except Exception as tap_err:
                            if is_wda_crashed(tap_err):
                                print("⚠️  WDA CRASH detected during WhatsApp button tap!")
                                return "restart"
                            print(f"Direct tap failed: {tap_err}, trying button detection...")
                            try:
                                if not click_didnt_get_code_button(log_coordinates=True):
                                    print("Failed to click button, skipping WhatsApp redirect handling")
                                    raise Exception("Could not handle WhatsApp redirect")
                                time.sleep(2)
                            except Exception as button_err:
                                if is_wda_crashed(button_err):
                                    print("⚠️  WDA CRASH detected during WhatsApp button detection!")
                                    return "restart"
                                raise

                        # Click "Send code via SMS" (note: "via" not "to")
                        try:
                            send_sms_button = driver.find_element(By.XPATH, '//*[@label="Send code via SMS" or @label="Send code to SMS"]')
                            send_sms_button.click()
                            print("Clicked 'Send code via SMS' - WhatsApp redirect handled")
                            time.sleep(2)
                        except Exception as sms_err:
                            if is_wda_crashed(sms_err):
                                print("⚠️  WDA CRASH detected during 'Send code via SMS' click!")
                                return "restart"
                            raise
                except Exception as wa_err:
                    if is_wda_crashed(wa_err):
                        print("⚠️  WDA CRASH detected during WhatsApp check!")
                        return "restart"
                    print("No WhatsApp redirect detected, code should be sent to SMS")

                # Now retrieve the SMS code - try twice with resend
                code_received = False
                code = None

                # First attempt - wait 30 seconds
                print("Waiting for SMS code from DaisySMS (first attempt)...")
                code = checkNumber(orderid, "daisy", key)

                if code != False:
                    code_received = True
                else:
                    print("No code received on first attempt. Looking for 'I didn't get the code' button...")

                    # Try multiple times to find and click the button (with retries)
                    max_button_attempts = 5
                    button_clicked = False

                    for button_attempt in range(max_button_attempts):
                        print(f"\n=== Button search attempt {button_attempt + 1}/{max_button_attempts} ===")
                        try:
                            # Scroll down to ensure button is visible using screen swipe
                            print("Scrolling down using screen swipe...")
                            try:
                                screen_size = driver.get_window_size()
                                # Swipe up from bottom to scroll down
                                driver.execute_script("mobile: dragFromToForDuration", {
                                    "fromX": screen_size['width'] / 2,
                                    "fromY": screen_size['height'] * 0.8,
                                    "toX": screen_size['width'] / 2,
                                    "toY": screen_size['height'] * 0.2,
                                    "duration": 0.5
                                })
                                print("Scroll swipe completed")
                                time.sleep(1)
                            except Exception as scroll_err:
                                # Check if this is a WDA crash
                                if is_wda_crashed(scroll_err):
                                    print("⚠️  WDA CRASH detected during scroll!")
                                    return "restart"  # Signal to restart entire account creation
                                print(f"Scroll failed: {scroll_err}, continuing anyway...")

                            # Tap directly on hardcoded coordinates first
                            print(f"Tapping 'I didn't get the code' button at hardcoded position (16, 338) - attempt {button_attempt + 1}...")
                            try:
                                driver.execute_script("mobile: tap", {"x": 16, "y": 338})
                                button_clicked = True
                                print("✓ Successfully tapped 'I didn't get the code' button!")
                                time.sleep(3)  # Wait for popup menu to appear
                                break
                            except Exception as tap_err:
                                # Check if this is a WDA crash
                                if is_wda_crashed(tap_err):
                                    print("⚠️  WDA CRASH detected during tap!")
                                    return "restart"  # Signal to restart entire account creation
                                print(f"Direct tap failed: {tap_err}, trying button detection as fallback...")
                                # Fallback: use button detection with coordinate logging
                                should_log = (button_attempt == 0 or button_attempt % 2 == 0)
                                try:
                                    if click_didnt_get_code_button(log_coordinates=should_log):
                                        button_clicked = True
                                        print("✓ Successfully clicked 'I didn't get the code' button!")
                                        time.sleep(3)  # Wait for popup menu to appear
                                        break
                                    else:
                                        print(f"Failed to find button on attempt {button_attempt + 1}, retrying...")
                                        time.sleep(2)
                                except Exception as button_detect_err:
                                    if is_wda_crashed(button_detect_err):
                                        print("⚠️  WDA CRASH detected during button detection!")
                                        return "restart"
                                    print(f"Button detection failed: {button_detect_err}")
                                    time.sleep(2)
                        except Exception as e:
                            # Check if this is a WDA crash
                            if is_wda_crashed(e):
                                print(f"⚠️  WDA CRASH detected on button attempt {button_attempt + 1}!")
                                return "restart"  # Signal to restart entire account creation
                            print(f"Error on button attempt {button_attempt + 1}: {e}")
                            time.sleep(2)

                    if button_clicked:
                        # Click SMS resend button from the popup menu - try multiple times
                        send_sms_clicked = False
                        for sms_attempt in range(10):  # Increased to 10 attempts
                            try:
                                # Check for all possible button labels (note: "via" not "to")
                                send_sms_button = driver.find_element(By.XPATH, '//*[@label="Send code via SMS" or @label="Send code to SMS" or @label="Resend code to SMS" or @label="Resend confirmation code"]')
                                send_sms_button.click()
                                button_text = send_sms_button.get_attribute('label')
                                print(f"Clicked '{button_text}'")
                                send_sms_clicked = True
                                time.sleep(2)
                                break
                            except:
                                if sms_attempt < 9:
                                    print(f"SMS resend button not found, waiting... (attempt {sms_attempt + 1}/10)")
                                    time.sleep(1)

                        if not send_sms_clicked:
                            print("Could not click SMS resend button, treating as failed attempt")
                        else:
                            # Second attempt - wait another 30 seconds
                            sms_requests_for_current_number = 2  # Track that we requested code a second time
                            print("Waiting for SMS code from DaisySMS (second attempt)...")
                            code = checkNumber(orderid, "daisy", key)

                            if code != False:
                                code_received = True
                            else:
                                print("No code received on second attempt either")
                    else:
                        print(f"Failed to click 'I didn't get the code' button after {max_button_attempts} attempts, skipping resend")

                # If we got the code (either first or second attempt), enter it
                if code_received and code != False:
                    print(f"Received code: {code}")
                    # Try to find the first text field and enter the code
                    try:
                        text_fields = driver.find_elements(By.XPATH, '//XCUIElementTypeTextField')
                        if len(text_fields) > 0:
                            # Click on the first input box
                            text_fields[0].click()
                            random_delay(0.5, 1)
                            # Type the code - Instagram should auto-fill across the 6 boxes
                            text_fields[0].send_keys(code)  # Fast typing like password
                            print(f"Entered confirmation code: {code}")

                            # Wait for Instagram to process the code
                            print("Waiting for Instagram to process confirmation code...")
                            time.sleep(3)

                            # Click Next button ONCE
                            try:
                                next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                                if next_button.is_enabled():
                                    next_button.click()
                                    print("Clicked Next after entering SMS code")
                                else:
                                    print("Next button not enabled, page may have auto-advanced")
                            except:
                                print("Next button not found, page likely auto-advanced")

                            # Mobile number step complete - password() will handle detecting and filling password page
                            print("SMS code step complete")
                            break
                        else:
                            print("No text fields found for code entry")
                    except Exception as e:
                        print(f"Error entering confirmation code: {e}")
                else:
                    # No code received after 2 attempts
                    print("No code received after 2 attempts.")
                    cancelNumber(orderid, "daisy", key)

                    # Check phone number strategy
                    if PHONE_NUMBER_STRATEGY == 'single':
                        print("Single number strategy enabled - restarting account creation instead of trying new number")
                        return False  # Restart entire account creation

                    # Multiple number strategy - try a new number
                    print("Multiple number strategy - renting new number...")

                    # Set retry flag so next attempt will clear the field
                    is_retry = True

                    # Click the back arrow until we reach the mobile number screen
                    print("Navigating back to phone number screen...")
                    max_back_attempts = 10
                    successfully_navigated_back = False

                    for back_attempt in range(max_back_attempts):
                        # Click the back arrow
                        try:
                            if click_back_arrow():
                                time.sleep(2)  # Wait for page transition

                                # Check if we're at the mobile number screen
                                try:
                                    mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
                                    if mobile_field:
                                        print("Successfully navigated back to mobile number screen")
                                        successfully_navigated_back = True
                                        break  # Exit the loop
                                except Exception as e:
                                    if is_wda_crashed(e):
                                        print("⚠️  WDA CRASH detected while checking mobile number screen!")
                                        return "restart"
                                    print(f"Not at mobile number screen yet, clicking back again (attempt {back_attempt + 1}/{max_back_attempts})...")
                                    continue
                            else:
                                print(f"Failed to click back arrow (attempt {back_attempt + 1}/{max_back_attempts})")

                                # After 5 failed attempts, try swipe gesture as fallback
                                if back_attempt >= 4:
                                    print("Trying swipe gesture to go back...")
                                    try:
                                        # Swipe from left edge to right (iOS back gesture)
                                        driver.execute_script("mobile: swipe", {
                                            "direction": "right",
                                            "startX": 10,
                                            "startY": 300
                                        })
                                        print("Performed back swipe gesture")
                                        time.sleep(2)

                                        # Check if we're at mobile number screen now
                                        try:
                                            mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
                                            if mobile_field:
                                                print("Successfully navigated back using swipe gesture")
                                                successfully_navigated_back = True
                                                break
                                        except Exception as e:
                                            if is_wda_crashed(e):
                                                print("⚠️  WDA CRASH detected after swipe gesture!")
                                                return "restart"
                                            pass
                                    except Exception as e:
                                        if is_wda_crashed(e):
                                            print("⚠️  WDA CRASH detected during swipe gesture!")
                                            return "restart"
                                        print(f"Swipe gesture failed: {e}")

                                time.sleep(2)
                        except Exception as e:
                            if is_wda_crashed(e):
                                print("⚠️  WDA CRASH detected during back navigation!")
                                return "restart"
                            print(f"Error during back navigation attempt {back_attempt + 1}: {e}")
                            time.sleep(2)

                    # If we still haven't navigated back after all attempts, restart the app as last resort
                    if not successfully_navigated_back:
                        print("Failed to navigate back after all attempts. Restarting Instagram app as fallback...")
                        try:
                            driver.terminate_app("com.burbn.instagram")
                            time.sleep(2)
                            driver.activate_app("com.burbn.instagram")
                            time.sleep(3)
                            print("Instagram app restarted. Will need to start account creation from beginning.")
                            # Break out of mobileNumber function to restart from createAccount
                            return False
                        except Exception as e:
                            if is_wda_crashed(e):
                                print("⚠️  WDA CRASH detected during app restart!")
                                return "restart"
                            print(f"Failed to restart app: {e}")

                    continue
        except Exception as e:
            print(f"Error in mobile number step: {str(e)}")
            try:
                print("Current page source:")
                print(driver.page_source)
            except:
                print("Unable to get page source")
            random_delay()

    # Log final tracking stats for this account's phone number attempts
    print(f"Phone number tracking: {phone_numbers_tried} number(s) tried, {sms_requests_for_current_number} SMS request(s) for successful number")
    return True


def password(accpw):
    """
    Handle password step:
    - Immediately start checking for password page
    - Once detected, type password and click Next
    - If after 10 seconds still on password page, click Next again
    """
    try:
        # Immediately start checking for password page
        print("Checking for password page...")
        password_field = None

        for check_attempt in range(15):  # Check for up to 15 seconds
            try:
                password_field = driver.find_element(By.XPATH, '//*[@label="Password"]')
                if password_field:
                    print(f"✓ Password page detected after {check_attempt + 1} seconds")
                    break
            except:
                if check_attempt < 14:
                    print(f"  Waiting for password page... ({check_attempt + 1}/15)")
                    time.sleep(1)

        if not password_field:
            print("❌ Password page not found after 15 seconds")
            return False

        # Type password (field is already activated after SMS code)
        password_field.send_keys(accpw)
        print("Entered password")
        time.sleep(1)  # Wait for Next button to become enabled

        # Click Next button
        print("Clicking Next button...")
        try:
            next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
            if next_button.is_enabled():
                next_button.click()
                print("Clicked Next button")
            else:
                print("⚠️  Next button not enabled, waiting...")
                time.sleep(2)
                next_button.click()
                print("Clicked Next button (after wait)")
        except Exception as e:
            print(f"Error clicking Next: {e}")
            return False

        # Continuously check for page transition for 10 seconds
        print("Checking for page transition (up to 10 seconds)...")
        page_transitioned = False

        for wait_check in range(10):
            time.sleep(1)
            try:
                driver.find_element(By.XPATH, '//*[@label="Password"]')
                # Still on password page
                print(f"  Still on password page... ({wait_check + 1}/10)")
            except:
                # Password field gone - successfully moved to next page
                print(f"✓ Successfully moved past password page after {wait_check + 1} seconds")
                page_transitioned = True
                break

        if page_transitioned:
            return True

        # Still on password page after 10 seconds - click Next again
        print("⚠️  Still on password page after 10 seconds, clicking Next again...")
        try:
            next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
            next_button.click()
            print("Clicked Next button again")

            # Continuously check for another 10 seconds
            print("Checking for page transition (second attempt, up to 10 seconds)...")
            for wait_check in range(10):
                time.sleep(1)
                try:
                    driver.find_element(By.XPATH, '//*[@label="Password"]')
                    print(f"  Still on password page... ({wait_check + 1}/10)")
                except:
                    print(f"✓ Successfully moved past password page on second attempt after {wait_check + 1} seconds")
                    return True

            print("❌ Still on password page after 2 Next button clicks")
            return False

        except Exception as e:
            print(f"Error clicking Next again: {e}")
            return False

    except Exception as e:
        print(f"Error in password step: {e}")
        return False


def birthday():
    try:
        # Wait a moment for the page to fully load
        time.sleep(2)

        # Try to find and click the birthday field - try multiple approaches
        birthday_field_clicked = False

        # First, check if picker wheels are already visible
        try:
            picker_wheels = driver.find_elements(By.XPATH, "//XCUIElementTypePickerWheel")
            if len(picker_wheels) >= 3:
                print(f"Picker wheels already visible ({len(picker_wheels)} found), proceeding to select date")
                birthday_field_clicked = True
        except:
            print("Picker wheels not found yet")

        # If pickers not visible, try to click the birthday field
        if not birthday_field_clicked:
            # Approach 1: Look for birthday text field
            try:
                birthday_field = driver.find_element(By.XPATH, "//XCUIElementTypeTextField")
                birthday_field.click()
                print("Clicked on birthday text field")
                birthday_field_clicked = True
                time.sleep(1)
            except:
                print("TextField not found, trying alternative methods...")

            # Approach 2: Look for button with birthday label
            if not birthday_field_clicked:
                try:
                    birthday_button = driver.find_element(By.XPATH, '//*[contains(@label, "Birthday") or contains(@label, "October") or contains(@label, "years old")]')
                    birthday_button.click()
                    print("Clicked on birthday button/label")
                    birthday_field_clicked = True
                    time.sleep(1)
                except:
                    print("Birthday button not found either")

        if not birthday_field_clicked:
            print("Could not activate birthday picker, page may not be ready")
            return False

        # Now scroll through all three picker wheels
        time.sleep(1)  # Wait for pickers to appear

        # Get all three picker wheels
        picker_wheels = driver.find_elements(By.XPATH, "//XCUIElementTypePickerWheel")
        if len(picker_wheels) < 3:
            print(f"Error: Expected 3 picker wheels, found {len(picker_wheels)}")
            return False

        monthPicker = picker_wheels[0]
        dayPicker = picker_wheels[1]
        yearPicker = picker_wheels[2]

        print(f"Initial values - Month: {monthPicker.text}, Day: {dayPicker.text}, Year: {yearPicker.text}")

        # Scroll month picker with truly random intensity
        # Use single swipe with high velocity variation for more randomness
        month_velocity = random.randint(200, 2000)  # Much wider range
        print(f"Scrolling month picker with velocity {month_velocity}...")
        driver.execute_script("mobile: swipe", {
            "direction": "down",
            "element": monthPicker,
            "velocity": month_velocity
        })
        time.sleep(random.uniform(0.3, 0.6))
        print(f"Selected month: {monthPicker.text}")

        # Scroll day picker with truly random intensity
        day_velocity = random.randint(200, 2000)  # Much wider range
        print(f"Scrolling day picker with velocity {day_velocity}...")
        driver.execute_script("mobile: swipe", {
            "direction": "down",
            "element": dayPicker,
            "velocity": day_velocity
        })
        time.sleep(random.uniform(0.3, 0.6))
        print(f"Selected day: {dayPicker.text}")

        # Scroll year picker with truly random intensity
        # Ensure account is 18+ years old (born 2007 or earlier)
        year_velocity = random.randint(500, 3000)  # Higher range for more year variation
        print(f"Scrolling year picker with velocity {year_velocity}...")
        driver.execute_script("mobile: swipe", {
            "direction": "down",
            "element": yearPicker,
            "velocity": year_velocity
        })
        time.sleep(random.uniform(0.3, 0.6))

        # Verify the year is 2007 or earlier (18+ years old)
        current_year = int(yearPicker.text)
        if current_year > 2007:
            print(f"Year {current_year} is too recent (under 18), scrolling to 2007 or earlier...")
            while int(yearPicker.text) > 2007:
                driver.execute_script("mobile: swipe", {
                    "direction": "down",
                    "element": yearPicker
                })
                time.sleep(0.2)

        print(f"Final birthday selection - Month: {monthPicker.text}, Day: {dayPicker.text}, Year: {yearPicker.text}")
        random_delay(1, 2)

        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
        next_button.click()
        print("Clicked Next after birthday")

        # Wait for page transition
        print("Waiting for page to load after birthday...")
        time.sleep(3)
        return True

    except Exception as e:
        print(f"Error in birthday function: {str(e)}")
        return False


def fullName(thename):
    try:
        name_field = driver.find_element(By.XPATH, '//*[@label="Full name"]')
        name_field.click()
        time.sleep(0.3)  # Reduced delay

        # Just type the name (hardcoded to "Maddie")
        name_field.send_keys("Maddie")  # Fast typing like password
        time.sleep(0.5)  # Reduced delay

        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
        next_button.click()
        print("Full name entered and Next clicked")

        # Wait for page transition
        print("Waiting for page to load after full name...")
        time.sleep(3)
        return True
    except Exception as e:
        print(f"Error in full name step: {str(e)}")
        return False


def doUsername():
    # Wait for username page to load
    print("Waiting for username page to load...")
    time.sleep(2)

    # Get username from file
    user = get_random_username_from_file()

    if not user:
        print("❌ No username available from usernames.txt")
        return False

    # Look for username field for 10 seconds total
    username_field = None
    print("Looking for username field (10 seconds max)...")
    for wait_attempt in range(10):  # 10 attempts × 1 second = 10 seconds
        try:
            username_field = driver.find_element(By.XPATH, '//*[@label="Username"]')
            if username_field:
                print(f"✓ Username field found after {wait_attempt + 1} seconds!")
                break
        except:
            if wait_attempt < 9:
                time.sleep(1)

    if not username_field:
        print("⚠️  Username field NOT found after 10 seconds")
        print("This likely means Instagram changed the step order")
        # Don't retry - return False immediately so detection can take over
        return False

    # Username field found, proceed with entering username
    try:
        username_field.clear()
        time.sleep(0.3)

        # Type username
        username_field.send_keys(user)  # Fast typing like password
        print(f"Entered username: {user}")

        random_delay(1, 2)

        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')

        # Try clicking Next up to 3 times
        next_click_attempts = 3
        for attempt in range(next_click_attempts):
            if next_button.is_enabled():
                next_button.click()
                print(f"Clicked Next after username (attempt {attempt + 1}/{next_click_attempts})")

                # First wait a moment for Instagram to process
                time.sleep(2)

                # Check for "is not available" error message
                try:
                    error_message = driver.find_element(By.XPATH, '//*[contains(@label, "is not available")]')
                    if error_message.is_displayed():
                        print(f"✗ Username '{user}' is not available (Instagram error message detected)")
                        # Clear the field and try a new username
                        try:
                            username_field = driver.find_element(By.XPATH, '//*[@label="Username"]')
                            username_field.clear()
                            print("Cleared username field")
                        except Exception as clear_error:
                            print(f"Could not clear field: {clear_error}")
                        # Username already deleted from file, recursively try another
                        return doUsername()
                except:
                    # No error message found, continue checking if page changed
                    pass

                # Wait up to 8 more seconds to see if we move to next page
                print("Waiting to see if page transitions...")
                page_changed = False
                for wait_check in range(8):  # Check for 8 more seconds (2 + 8 = 10 total)
                    time.sleep(1)
                    try:
                        # Check if we're still on username page
                        driver.find_element(By.XPATH, '//*[@label="Username"]')
                        # Still on username page after this second
                        if wait_check == 7:  # After 8 more seconds (10 total)
                            print(f"Still on username page after 10 seconds (attempt {attempt + 1})")
                            page_changed = False
                            break
                    except:
                        # Username field not found - we moved to next page!
                        print(f"Successfully moved past username page after {wait_check + 3} seconds")
                        page_changed = True
                        break

                if page_changed:
                    # Username was accepted and already deleted from file
                    return user  # Success!
                elif attempt < next_click_attempts - 1:
                    # Still on username page - try clicking Next again
                    print(f"Retrying Next button click...")
                    try:
                        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                    except:
                        print("Next button not found for retry")
                        break
                else:
                    # Final attempt failed - username not available on Instagram
                    print(f"Username '{user}' already exists on Instagram")
                    # Username was already deleted from file when we got it, so just try a new one
                    return doUsername()
            else:
                print("Next button not enabled, waiting...")
                random_delay(1, 2)

        print(f"Username {user} not accepted after {next_click_attempts} attempts")
        return False
    except Exception as e:
        print(f"Error in username step: {str(e)}")
        return False


def click_next_after_username():
    try:
        # Check if "I agree" button appears after username
        agree_button = driver.find_element(By.XPATH, '//*[@label="I agree" or @label="I Agree"]')
        if agree_button.is_displayed():
            agree_button.click()
            print("Clicked 'I agree' after username")
            time.sleep(3)  # Wait after clicking
            return True
    except:
        # "I agree" not found, try clicking Next button
        try:
            next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
            next_button.click()
            print("Clicked 'Next' after username")
            time.sleep(3)
            return True
        except:
            print("Neither 'I agree' nor 'Next' button found after username")
            pass
    return True


def save_login():
    max_attempts = 5
    time.sleep(2)
    for attempt in range(max_attempts):
        try:
            not_now_button = driver.find_element(By.XPATH, '//*[contains(@label,"Not") and contains(@label,"now")]')
            if not_now_button.is_enabled():
                not_now_button.click()
                print("Clicked 'Not Now' for save login info")
                time.sleep(2)  # Wait after clicking
                return True
            else:
                print(f"'Not Now' button found but not enabled (Attempt {attempt + 1})")
        except:
            # Check if we're already on the birthday screen (Save Login screen was skipped)
            try:
                birthday_field = driver.find_element(By.XPATH, '//*[contains(@label, "Birthday") or contains(@label, "birthday")]')
                if birthday_field:
                    print("'Save Login Info' screen was skipped, already on birthday page")
                    return True
            except:
                pass

            if attempt < max_attempts - 1:
                time.sleep(1)  # Wait before next attempt
            else:
                # Last attempt - check once more if we're on next screen
                print("'Not Now' button not found after multiple attempts")
                print("Checking if 'Save Login Info' screen was skipped...")
                try:
                    birthday_field = driver.find_element(By.XPATH, '//*[contains(@label, "Birthday") or contains(@label, "birthday")]')
                    print("Confirmed: 'Save Login Info' screen was skipped, moving to birthday step")
                    return True
                except:
                    print("Not on birthday screen either, something went wrong")
                    return False

    return True  # Default to success if we get here


def agree():
    try:
        # Try to find "I agree" button
        agree_button = driver.find_element(By.XPATH, '//*[@label="I agree" or @label="I Agree"]')
        agree_button.click()
        print("Clicked 'I agree'")

        # Wait for page to change after clicking "I agree", then check what page we landed on
        print("Waiting for page to load after 'I agree'...")
        page_loaded = False
        page_type = None  # Will be "human_verification", "profile_picture", or "welcome"
        max_wait_time = 20  # Maximum 20 seconds

        for check_attempt in range(max_wait_time):
            print(f"  Checking for page change... ({check_attempt + 1}/{max_wait_time})")

            # Check for "Confirm that you're human" page
            # Method 1: Page source check (most reliable)
            try:
                page_source = driver.page_source
                if "Confirm that you" in page_source and "human" in page_source:
                    page_type = "human_verification"
                    page_loaded = True
                    break
            except:
                pass

            # Method 2: Look for "to use your account" text
            try:
                use_account = driver.find_element(By.XPATH, '//*[contains(@label, "to use your account")]')
                if use_account:
                    page_type = "human_verification"
                    page_loaded = True
                    break
            except:
                pass

            # Check for profile picture screen (normal flow)
            try:
                add_pic = driver.find_element(By.XPATH, '//*[@label="Add picture" or @label="Skip"]')
                if add_pic:
                    page_type = "profile_picture"
                    page_loaded = True
                    break
            except:
                pass

            # Check for welcome screen
            try:
                welcome = driver.find_element(By.XPATH, '//*[contains(@label, "Welcome to") or contains(@label, "fun")]')
                if welcome:
                    page_type = "welcome"
                    page_loaded = True
                    break
            except:
                pass

            time.sleep(1)

        # Handle based on what page we landed on
        if page_type == "human_verification":
            print("❌ CRITICAL: 'Confirm that you're human' page detected!")
            print("This account has been flagged by Instagram")
            print("Treating account as FAILED - will restart account creation")
            return "human_verification_failed"
        elif page_type == "profile_picture":
            print(f"✓ Profile picture screen loaded successfully after {check_attempt + 1} seconds")
        elif page_type == "welcome":
            print(f"✓ Welcome screen loaded after {check_attempt + 1} seconds")
        else:
            # Page didn't load after 20 seconds - click I agree again
            print(f"⚠️  Page didn't load after {max_wait_time} seconds, clicking 'I agree' again...")
            try:
                agree_button = driver.find_element(By.XPATH, '//*[@label="I agree" or @label="I Agree"]')
                agree_button.click()
                print("Clicked 'I agree' again")

                # Check for page change again (up to 10 more seconds)
                for retry_attempt in range(10):
                    print(f"  Retry checking for page change... ({retry_attempt + 1}/10)")

                    # Check for profile picture screen
                    try:
                        add_pic = driver.find_element(By.XPATH, '//*[@label="Add picture" or @label="Skip"]')
                        if add_pic:
                            print(f"✓ Profile picture screen loaded on retry after {retry_attempt + 1} seconds")
                            break
                    except:
                        pass

                    # Check for human verification
                    try:
                        page_source = driver.page_source
                        if "Confirm that you" in page_source and "human" in page_source:
                            print("❌ CRITICAL: 'Confirm that you're human' page detected!")
                            return "human_verification_failed"
                    except:
                        pass

                    time.sleep(1)
            except:
                print("Could not find 'I agree' button for retry")

        # Check for "Try again later" pop-up
        try:
            try_again_later = driver.find_element(By.XPATH, '//*[contains(@label, "Try again later")]')
            if try_again_later.is_displayed():
                print("'Try again later' pop-up detected. Restarting the process.")
                driver.terminate_app("com.burbn.instagram")
                return "restart"
        except:
            # If the element is not found, it means the pop-up didn't appear, so we can continue
            pass

        return True
    except:
        # "I agree" button not found, check if we're already on username page
        print("'I agree' button not found, checking if already on username page...")
        try:
            username_field = driver.find_element(By.XPATH, '//*[@label="Username"]')
            if username_field:
                print("Already on username page, 'I agree' screen was skipped")
                return True
        except:
            pass

        # Also check for "Create a username" text
        try:
            create_username = driver.find_element(By.XPATH, '//*[contains(@label, "Create a username") or contains(@label, "username")]')
            if create_username:
                print("Already on username page (found 'Create a username'), 'I agree' screen was skipped")
                return True
        except:
            pass

        print("Neither 'I agree' button nor username page found")
        return False


def detect_profile_edit_screen():
    """Detect what screen we're on during profile editing to handle popups"""
    try:
        page_source = driver.page_source

        # Check for cookies popup
        try:
            allow_cookies = driver.find_element(By.XPATH, '//*[@label="Allow all cookies" or contains(@label, "Allow all cookies")]')
            print("🔍 Detected: Cookies popup on screen")
            return "cookies_popup"
        except:
            pass

        # Check for notifications popup
        try:
            dont_allow = driver.find_element(By.XPATH, "//*[@label=\"Don't Allow\"]")
            print("🔍 Detected: Notifications popup on screen")
            return "notifications_popup"
        except:
            pass

        # Check for "Create your avatar" popup
        try:
            not_now = driver.find_element(By.XPATH, '//*[@label="Not now" or @label="Not Now"]')
            if "avatar" in page_source.lower():
                print("🔍 Detected: Create avatar popup on screen")
                return "avatar_popup"
        except:
            pass

        # Check for Links page (BEFORE checking Edit Profile page)
        # Links page shows "Add external link" button
        try:
            add_external = driver.find_element(By.XPATH, '//*[@label="Add external link"]')
            print("🔍 Detected: Links page (showing add external link)")
            return "links_page"
        except:
            pass

        # Check for URL input field
        try:
            text_field = driver.find_element(By.XPATH, '//XCUIElementTypeTextField')
            if "url" in page_source.lower() or "link" in page_source.lower():
                print("🔍 Detected: URL input field visible")
                return "url_input"
        except:
            pass

        # Check for Edit Profile page
        # The most reliable way is to check for the "Edit profile" header text
        # Combined with checking that we're NOT on Links page (no "Add external link")

        # First, make sure we're NOT on Links page
        try:
            driver.find_element(By.XPATH, '//*[@label="Add external link"]')
            # If we found "Add external link", we're on Links page, not Edit Profile
            # Skip Edit Profile detection
        except:
            # Good, we're not on Links page, continue checking for Edit Profile

            # Method 1: Check for "Edit profile" header/title
            edit_profile_header_found = False
            try:
                # Look for "Edit profile" as navigation bar title or static text
                driver.find_element(By.XPATH, '//XCUIElementTypeNavigationBar[@name="Edit profile"] | //XCUIElementTypeStaticText[@label="Edit profile" or @value="Edit profile"]')
                edit_profile_header_found = True
                print("🔍 Detected: Edit Profile page (header found)")
                return "edit_profile"
            except:
                pass

            # Method 2: Check for Bio field to be truly on Edit Profile page (not Links page)
            # Try multiple methods to detect Bio field
            bio_found = False

            # Look for Bio as XCUIElementTypeButton
            try:
                driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Bio"]')
                bio_found = True
            except:
                pass

            # Look for Bio as any element type
            if not bio_found:
                try:
                    driver.find_element(By.XPATH, '//*[@label="Bio"]')
                    bio_found = True
                except:
                    pass

            # Look for Bio as StaticText
            if not bio_found:
                try:
                    driver.find_element(By.XPATH, '//XCUIElementTypeStaticText[@label="Bio"]')
                    bio_found = True
                except:
                    pass

            if bio_found:
                # Also check for other Edit Profile elements to be sure
                # Check for Name field
                try:
                    driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Name"] | //XCUIElementTypeStaticText[@label="Name"] | //*[@label="Name"]')
                    print("🔍 Detected: Edit Profile page (Bio + Name found)")
                    return "edit_profile"
                except:
                    pass

                # Check for Username field
                try:
                    driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Username"] | //XCUIElementTypeStaticText[@label="Username"] | //*[@label="Username"]')
                    print("🔍 Detected: Edit Profile page (Bio + Username found)")
                    return "edit_profile"
                except:
                    pass

                # Check for Pronouns field
                try:
                    driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Pronouns"] | //XCUIElementTypeStaticText[@label="Pronouns"] | //*[@label="Pronouns"]')
                    print("🔍 Detected: Edit Profile page (Bio + Pronouns found)")
                    return "edit_profile"
                except:
                    pass

                # Check for Links field (with count indicator like "1")
                try:
                    driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Links"] | //XCUIElementTypeStaticText[@label="Links"]')
                    print("🔍 Detected: Edit Profile page (Bio + Links field found)")
                    return "edit_profile"
                except:
                    pass

                # Check for "Edit picture or avatar" text (unique to Edit Profile page)
                try:
                    driver.find_element(By.XPATH, '//*[contains(@label, "Edit picture") or contains(@label, "Edit avatar")]')
                    print("🔍 Detected: Edit Profile page (Bio + Edit picture found)")
                    return "edit_profile"
                except:
                    pass

                # If Bio exists but we can't confirm other fields, still assume Edit Profile
                print("🔍 Detected: Page with Bio field (assuming Edit Profile)")
                return "edit_profile"

        # Check for Profile page
        try:
            edit_profile = driver.find_element(By.XPATH, '//*[@label="Edit profile"]')
            print("🔍 Detected: Profile page")
            return "profile"
        except:
            pass

        print("🔍 Screen detection: Unknown screen")
        return None
    except Exception as e:
        print(f"Error detecting screen: {e}")
        return None


def handle_popups_during_link_addition():
    """Handle any popups that appear during link addition process"""
    handled = False

    # Check for cookies popup
    try:
        allow_cookies = driver.find_element(By.XPATH, '//*[@label="Allow all cookies" or contains(@label, "Allow all cookies")]')
        allow_cookies.click()
        print("✓ Dismissed cookies popup during link addition")
        handled = True
        time.sleep(1)
        return True
    except:
        pass

    # Check for notifications popup
    try:
        dont_allow = driver.find_element(By.XPATH, "//*[@label=\"Don't Allow\"]")
        dont_allow.click()
        print("✓ Dismissed notifications popup during link addition")
        handled = True
        time.sleep(1)
        return True
    except:
        pass

    # Check for "Not Now" buttons
    try:
        not_now = driver.find_element(By.XPATH, '//*[@label="Not Now" or @label="Not now"]')
        not_now.click()
        print("✓ Dismissed 'Not Now' popup during link addition")
        handled = True
        time.sleep(1)
        return True
    except:
        pass

    return handled


def addOnlyFansLink():
    """Add OnlyFans link to Instagram profile"""
    try:
        print("Adding OnlyFans link to profile...")

        # Click profile button (bottom right) with multiple detection methods
        max_attempts = 10
        profile_clicked = False
        for attempt in range(max_attempts):
            # Method 1: Look for Profile as XCUIElementTypeButton
            try:
                profile_button = driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Profile"]')
                profile_button.click()
                print("Clicked profile button (Method 1: Button)")
                profile_clicked = True
                time.sleep(2)
                break
            except:
                pass

            # Method 2: Look for Profile as StaticText
            try:
                profile_button = driver.find_element(By.XPATH, '//XCUIElementTypeStaticText[@label="Profile"]')
                profile_button.click()
                print("Clicked profile button (Method 2: StaticText)")
                profile_clicked = True
                time.sleep(2)
                break
            except:
                pass

            # Method 3: Look for Profile as any element type
            try:
                profile_button = driver.find_element(By.XPATH, '//*[@label="Profile"]')
                profile_button.click()
                print("Clicked profile button (Method 3: Any element)")
                profile_clicked = True
                time.sleep(2)
                break
            except:
                pass

            # Method 4: Look for Profile by @name attribute
            try:
                profile_button = driver.find_element(By.XPATH, '//*[@name="Profile"]')
                profile_button.click()
                print("Clicked profile button (Method 4: @name)")
                profile_clicked = True
                time.sleep(2)
                break
            except:
                pass

            print(f"Profile button not found with any method (attempt {attempt + 1}/{max_attempts}), waiting...")
            time.sleep(1)

        if not profile_clicked:
            print("Could not find profile button with any detection method")
            print("🔍 Scanning screen to understand current state...")
            detected = detect_profile_edit_screen()
            return False

        # Click "Edit profile" button
        edit_profile_clicked = False
        max_edit_attempts = 10
        for attempt in range(max_edit_attempts):
            # Check for and handle any popups
            if attempt > 0:
                print(f"Checking for popups before retry {attempt + 1}...")
                handle_popups_during_link_addition()

            try:
                edit_profile_button = driver.find_element(By.XPATH, '//*[@label="Edit profile"]')
                edit_profile_button.click()
                print("Clicked 'Edit profile'")
                edit_profile_clicked = True
                time.sleep(2)
                break
            except:
                print(f"Edit profile button not found (attempt {attempt + 1}/{max_edit_attempts})")

                # Every 3 attempts, do a screen scan
                if (attempt + 1) % 3 == 0:
                    print("🔍 Performing screen scan...")
                    detected = detect_profile_edit_screen()
                    if detected in ["cookies_popup", "notifications_popup", "avatar_popup"]:
                        print(f"Found blocking popup: {detected}, attempting to dismiss...")
                        handle_popups_during_link_addition()

                time.sleep(2)

        if not edit_profile_clicked:
            print("⚠️  Could not click Edit profile button")
            print("🔍 Screen scan:")
            detected = detect_profile_edit_screen()
            print(f"Current screen state: {detected}")

        # Handle "Create your avatar" popup if it appears
        print("Checking for 'Create your avatar' popup...")
        avatar_popup_found = False

        # Try multiple methods to detect and dismiss the popup
        try:
            # Method 1: Look for "Not now" button
            not_now_button = driver.find_element(By.XPATH, '//*[@label="Not now"]')
            if not_now_button.is_displayed():
                not_now_button.click()
                print("✓ Dismissed 'Create your avatar' popup (Method 1: Not now)")
                avatar_popup_found = True
                time.sleep(2)
        except Exception as e:
            print(f"Method 1 (Not now) failed: {e}")

        # Method 2: Try "Not Now" with capital N
        if not avatar_popup_found:
            try:
                not_now_button = driver.find_element(By.XPATH, '//*[@label="Not Now"]')
                if not_now_button.is_displayed():
                    not_now_button.click()
                    print("✓ Dismissed 'Create your avatar' popup (Method 2: Not Now)")
                    avatar_popup_found = True
                    time.sleep(2)
            except Exception as e:
                print(f"Method 2 (Not Now) failed: {e}")

        # Method 3: Look for any button containing "Not" or "now"
        if not avatar_popup_found:
            try:
                not_now_button = driver.find_element(By.XPATH, '//*[contains(@label, "Not") and contains(@label, "ow")]')
                if not_now_button.is_displayed():
                    not_now_button.click()
                    print("✓ Dismissed 'Create your avatar' popup (Method 3: Contains 'Not')")
                    avatar_popup_found = True
                    time.sleep(2)
            except Exception as e:
                print(f"Method 3 (Contains) failed: {e}")

        if not avatar_popup_found:
            print("No 'Create your avatar' popup found, continuing...")

        # Click "Links" row (look for "Add links" text or "Links" label)
        # Increased retries and wait time to handle popups
        links_clicked = False
        max_link_attempts = 15
        for attempt in range(max_link_attempts):
            # First, check for and handle any popups
            if attempt > 0:
                print(f"Checking for popups before retry {attempt + 1}...")
                handle_popups_during_link_addition()

            try:
                links_button = driver.find_element(By.XPATH, '//*[@label="Links" or contains(@label, "Add links")]')
                links_button.click()
                print("Clicked 'Links'")
                links_clicked = True
                time.sleep(2)
                break
            except:
                print(f"Links button not found (attempt {attempt + 1}/{max_link_attempts})")

                # Every 5 attempts, do a comprehensive screen scan
                if (attempt + 1) % 5 == 0:
                    print("🔍 Performing comprehensive screen scan...")
                    detected = detect_profile_edit_screen()
                    if detected in ["cookies_popup", "notifications_popup", "avatar_popup"]:
                        print(f"Found blocking popup: {detected}, attempting to dismiss...")
                        handle_popups_during_link_addition()

                time.sleep(2)  # Longer wait between retries

        if not links_clicked:
            print("❌ CRITICAL: Failed to click Links button after all attempts")
            print("🔍 Final screen scan before giving up...")
            detected = detect_profile_edit_screen()
            print(f"Current screen state: {detected}")
            return False

        # Click "Add external link"
        add_link_clicked = False
        max_add_link_attempts = 15
        for attempt in range(max_add_link_attempts):
            # Check for and handle any popups
            if attempt > 0:
                print(f"Checking for popups before retry {attempt + 1}...")
                handle_popups_during_link_addition()

            try:
                add_external_link = driver.find_element(By.XPATH, '//*[@label="Add external link"]')
                add_external_link.click()
                print("Clicked 'Add external link'")
                add_link_clicked = True
                time.sleep(2)
                break
            except:
                print(f"Add external link button not found (attempt {attempt + 1}/{max_add_link_attempts})")

                # Every 5 attempts, do a comprehensive screen scan
                if (attempt + 1) % 5 == 0:
                    print("🔍 Performing comprehensive screen scan...")
                    detected = detect_profile_edit_screen()
                    if detected in ["cookies_popup", "notifications_popup", "avatar_popup"]:
                        print(f"Found blocking popup: {detected}, attempting to dismiss...")
                        handle_popups_during_link_addition()

                time.sleep(2)  # Longer wait between retries

        if not add_link_clicked:
            print("❌ CRITICAL: Failed to click Add external link after all attempts")
            print("🔍 Final screen scan before giving up...")
            detected = detect_profile_edit_screen()
            print(f"Current screen state: {detected}")
            return False

        # The URL field is already focused after clicking "Add external link"
        # Just type the OnlyFans link directly without clicking
        link_typed = False
        onlyfans_link = "onlyfans.com/uwumaddie/c46"
        max_typing_attempts = 10

        for attempt in range(max_typing_attempts):
            # Check for and handle any popups
            if attempt > 0:
                print(f"Checking for popups before retry {attempt + 1}...")
                handle_popups_during_link_addition()

            try:
                # Find the text field and type directly
                text_field = driver.find_element(By.XPATH, '//XCUIElementTypeTextField')
                text_field.send_keys(onlyfans_link)  # Fast typing like password
                print(f"Entered OnlyFans link: {onlyfans_link}")
                link_typed = True
                time.sleep(1)
                break
            except Exception as e:
                print(f"Error typing OnlyFans link (attempt {attempt + 1}/{max_typing_attempts}): {e}")

                # Every 3 attempts, do a comprehensive screen scan
                if (attempt + 1) % 3 == 0:
                    print("🔍 Performing comprehensive screen scan...")
                    detected = detect_profile_edit_screen()
                    if detected in ["cookies_popup", "notifications_popup", "avatar_popup"]:
                        print(f"Found blocking popup: {detected}, attempting to dismiss...")
                        handle_popups_during_link_addition()

                time.sleep(2)  # Longer wait between retries

        if not link_typed:
            print("❌ CRITICAL: Failed to type OnlyFans link after all attempts")
            print("🔍 Final screen scan before giving up...")
            detected = detect_profile_edit_screen()
            print(f"Current screen state: {detected}")
            return False

        # Click "Done" button
        done_clicked = False
        max_done_attempts = 15
        for attempt in range(max_done_attempts):
            # Check for and handle any popups
            if attempt > 0:
                print(f"Checking for popups before retry {attempt + 1}...")
                handle_popups_during_link_addition()

            try:
                done_button = driver.find_element(By.XPATH, '//*[@label="Done"]')
                done_button.click()
                print("Clicked 'Done'")
                done_clicked = True
                print("Waiting 3 seconds for page to settle after clicking Done...")
                time.sleep(3)
                break
            except:
                print(f"Done button not found (attempt {attempt + 1}/{max_done_attempts})")

                # Every 5 attempts, do a comprehensive screen scan
                if (attempt + 1) % 5 == 0:
                    print("🔍 Performing comprehensive screen scan...")
                    detected = detect_profile_edit_screen()
                    if detected in ["cookies_popup", "notifications_popup", "avatar_popup"]:
                        print(f"Found blocking popup: {detected}, attempting to dismiss...")
                        handle_popups_during_link_addition()

                time.sleep(2)  # Longer wait between retries

        if not done_clicked:
            print("❌ CRITICAL: Failed to click Done button after all attempts - OnlyFans link was not saved")
            print("🔍 Final screen scan before giving up...")
            detected = detect_profile_edit_screen()
            print(f"Current screen state: {detected}")
            return False

        # Navigate back to Edit profile page using back arrow (top left)
        # Retry clicking back arrow if we're still on the Links page
        print("Navigating back to Edit profile page...")

        for back_attempt in range(3):
            print(f"Clicking back arrow (attempt {back_attempt + 1}/3)...")
            if click_back_arrow():
                print("Clicked back arrow")
            else:
                print("Failed to click back arrow")

            # Wait and check if we're on Edit Profile page
            time.sleep(2)

            # Check if Bio field is visible (means we're on Edit Profile page)
            try:
                bio_check = driver.find_element(By.XPATH, '//*[@label="Bio"]')
                if bio_check:
                    print("✓ Successfully navigated to Edit profile page")
                    break
            except:
                # Bio not found, check if still on Links page
                current_screen = detect_profile_edit_screen()
                if current_screen == "links_page":
                    print(f"⚠️  Still on Links page, clicking back arrow again...")
                    continue
                else:
                    # On some other page, assume it's Edit Profile
                    print(f"On screen: {current_screen}, continuing...")
                    break

        # Add bio
        print("Adding bio to profile...")
        try:
            # Read random bio from bios.txt
            with open("bios.txt", "r", encoding="utf-8") as f:
                bios_content = f.read()

            # Split by | to get individual bios
            bios = [bio.strip() for bio in bios_content.split("|") if bio.strip()]

            if len(bios) == 0:
                print("No bios found in bios.txt")
            else:
                # Pick random bio
                selected_bio = random.choice(bios)
                print(f"Selected bio: {selected_bio[:50]}...")  # Print first 50 chars

                # Click Bio field with retry logic and multiple detection methods
                bio_field_clicked = False
                for attempt in range(5):
                    # Method 1: Look for Bio as XCUIElementTypeButton
                    try:
                        bio_field = driver.find_element(By.XPATH, '//XCUIElementTypeButton[@label="Bio"]')
                        bio_field.click()
                        print("Clicked Bio field (Method 1: Button)")
                        bio_field_clicked = True
                        time.sleep(1)
                        break
                    except:
                        pass

                    # Method 2: Look for Bio as StaticText
                    try:
                        bio_field = driver.find_element(By.XPATH, '//XCUIElementTypeStaticText[@label="Bio"]')
                        bio_field.click()
                        print("Clicked Bio field (Method 2: StaticText)")
                        bio_field_clicked = True
                        time.sleep(1)
                        break
                    except:
                        pass

                    # Method 3: Look for Bio as any element type
                    try:
                        bio_field = driver.find_element(By.XPATH, '//*[@label="Bio"]')
                        bio_field.click()
                        print("Clicked Bio field (Method 3: Any element)")
                        bio_field_clicked = True
                        time.sleep(1)
                        break
                    except:
                        pass

                    # Method 4: Look for Bio by @name attribute
                    try:
                        bio_field = driver.find_element(By.XPATH, '//*[@name="Bio"]')
                        bio_field.click()
                        print("Clicked Bio field (Method 4: @name)")
                        bio_field_clicked = True
                        time.sleep(1)
                        break
                    except:
                        pass

                    print(f"Bio field not found with any method (attempt {attempt + 1}/5), waiting...")
                    time.sleep(1)

                if not bio_field_clicked:
                    print("⚠️  Could not find Bio field after 5 attempts with all methods")
                    print("🔍 Running final screen detection to understand current state...")
                    final_detection = detect_profile_edit_screen()
                    print(f"Current screen: {final_detection}")
                    print("✓ OnlyFans link was added successfully, returning True (skipping bio)")
                    return True  # Still return True as link was added successfully

                # Find the text view and enter bio
                bio_text_view = driver.find_element(By.XPATH, '//XCUIElementTypeTextView')
                bio_text_view.click()
                time.sleep(0.5)

                # Clear any existing text
                bio_text_view.clear()
                time.sleep(0.3)

                # Enter bio (preserving line breaks)
                bio_text_view.send_keys(selected_bio)
                print("Entered bio")
                time.sleep(1)

                # Click Done at the top
                done_button = driver.find_element(By.XPATH, '//*[@label="Done"]')
                done_button.click()
                print("Clicked 'Done' after bio")
                time.sleep(2)

        except FileNotFoundError:
            print("⚠️  bios.txt not found, skipping bio addition")
        except Exception as e:
            print(f"Error adding bio: {e}")

        print("OnlyFans link and bio successfully added to profile!")
        return True

    except Exception as e:
        print(f"Error adding OnlyFans link: {str(e)}")
        return False


def skip_profile_picture():
    """Add a profile picture from Picz album"""
    try:
        # Step 1: Click "Add picture" button
        print("Looking for 'Add picture' button...")
        add_picture_button = driver.find_element(By.XPATH, '//*[@label="Add picture"]')
        add_picture_button.click()
        print("Clicked 'Add picture'")
        time.sleep(2)

        # Step 2: Click "Choose From Camera Roll" (with capital or lowercase 'from')
        print("Looking for 'Choose From Camera Roll'...")
        camera_roll_button = driver.find_element(By.XPATH, '//*[@label="Choose From Camera Roll" or @label="Choose from Camera Roll"]')
        camera_roll_button.click()
        print("Clicked 'Choose From/from Camera Roll'")
        time.sleep(2)

        # Step 3: Click on "Albums" tab (starts on "Photos" tab by default)
        print("Switching to Albums tab...")
        albums_tab = driver.find_element(By.XPATH, '//*[@label="Albums"]')
        albums_tab.click()
        print("Clicked 'Albums' tab")
        time.sleep(1)

        # Step 4: Click on "Picz" album
        print("Looking for 'Picz' album...")
        picz_album = driver.find_element(By.XPATH, '//*[@label="Picz"]')
        picz_album.click()
        print("Opened 'Picz' album")
        time.sleep(5)  # Wait longer for album and photos to load

        # Step 5: Get all photos and select one randomly
        print("Finding all photos in album...")

        # Scroll down to trigger photo grid loading
        print("Scrolling down to load photos...")
        try:
            screen_size = driver.get_window_size()
            # Swipe down to load photo grid
            driver.execute_script("mobile: dragFromToForDuration", {
                "fromX": screen_size['width'] / 2,
                "fromY": screen_size['height'] * 0.8,
                "toX": screen_size['width'] / 2,
                "toY": screen_size['height'] * 0.3,
                "duration": 0.5
            })
            time.sleep(2)
            print("Scroll completed, photos should be loaded")
        except Exception as scroll_err:
            print(f"Scroll failed: {scroll_err}, continuing anyway...")

        # Use Method 3 (Images) - this is what worked!
        photo_cells = []
        try:
            images = driver.find_elements(By.XPATH, '//XCUIElementTypeImage')
            print(f"Found {len(images)} images")
            for img in images:
                try:
                    if img.is_displayed():
                        size = img.size
                        if size['width'] > 10 and size['height'] > 10:
                            photo_cells.append(img)
                except:
                    pass
        except Exception as e:
            print(f"Error finding images: {e}")
            return False

        print(f"Total valid photos found: {len(photo_cells)}")

        if len(photo_cells) > 0:
            # Select random photo from valid cells
            random_photo = random.choice(photo_cells)
            print(f"Selecting random photo from {len(photo_cells)} available...")
            random_photo.click()
            print("✓ Selected random photo")
            time.sleep(1)
        else:
            print("❌ No valid photos found")
            return False

        # Step 6: Click "Done" button
        print("Looking for 'Done' button...")
        done_button = driver.find_element(By.XPATH, '//*[@label="Done"]')
        done_button.click()
        print("Clicked 'Done' button")

        # Step 7: Wait 5 seconds for Instagram to process the profile picture
        time.sleep(5)
        print("✓ Profile picture added successfully!")
        return True

    except Exception as e:
        print(f"Error adding profile picture: {e}")
        # Try to go back to home if something failed
        try:
            driver.execute_script("mobile: pressButton", {"name": "home"})
        except:
            pass
        return False


def is_account_creation_complete():
    """Check if we've completed account creation and reached the main Instagram screen"""
    try:
        page_source = driver.page_source

        # IMPORTANT: First check if we're still on profile picture screen
        # Instagram shows bottom nav even during profile picture step, so check this first
        try:
            profile_pic_elements = driver.find_element(By.XPATH, '//*[@label="Add picture" or @label="Skip" or contains(@label, "Add a profile picture")]')
            if profile_pic_elements:
                print("Still on profile picture screen - NOT complete yet")
                return False
        except:
            pass

        # Check for main Instagram elements (Home, Search, Profile tabs)
        try:
            home_tab = driver.find_element(By.XPATH, '//*[@label="Home"]')
            if home_tab:
                print("Account creation complete - detected Home tab")
                return True
        except:
            pass

        # Check for Search and Explore tab
        try:
            search_tab = driver.find_element(By.XPATH, '//*[@label="Search and Explore" or @label="Search"]')
            if search_tab:
                print("Account creation complete - detected Search tab")
                return True
        except:
            pass

        # Check for Profile tab at bottom
        try:
            profile_tab = driver.find_element(By.XPATH, '//*[@label="Profile" and @type="XCUIElementTypeButton"]')
            if profile_tab:
                print("Account creation complete - detected Profile tab")
                return True
        except:
            pass

        # Check for Reels tab
        try:
            reels_tab = driver.find_element(By.XPATH, '//*[@label="Reels"]')
            if reels_tab:
                print("Account creation complete - detected Reels tab")
                return True
        except:
            pass

        # Alternative: Check for main feed elements
        if "feed" in page_source.lower() or "new posts" in page_source.lower():
            print("Account creation complete - detected feed")
            return True

        # Check for notification/welcome screens that come after account creation
        try:
            turn_on_notifications = driver.find_element(By.XPATH, '//*[contains(@label, "Turn on") and contains(@label, "notification")]')
            if turn_on_notifications:
                print("Account creation complete - detected notification prompt")
                return True
        except:
            pass

        return False
    except:
        return False


def detect_current_step():
    """Detect which account creation step we're currently on by scanning the screen"""
    try:
        page_source = driver.page_source

        # First check if account creation is complete
        if is_account_creation_complete():
            print("Detected: Account creation complete!")
            return "complete"

        # Check for profile picture screen
        try:
            skip_button = driver.find_element(By.XPATH, '//*[@label="Skip"]')
            if "Add a profile picture" in page_source or "profile picture" in page_source.lower():
                print("Detected: Profile picture screen")
                return "profile_picture"
        except:
            pass

        # Check for I agree screen (check early since it can appear at various points)
        try:
            agree_button = driver.find_element(By.XPATH, '//*[@label="I agree" or @label="I Agree"]')
            if agree_button:
                print("Detected: I agree screen")
                return "agree"
        except:
            pass

        # Check for username screen
        try:
            username_field = driver.find_element(By.XPATH, '//*[@label="Username"]')
            if username_field:
                print("Detected: Username screen")
                return "username"
        except:
            pass

        # Check for full name screen
        try:
            name_field = driver.find_element(By.XPATH, '//*[@label="Full name"]')
            if name_field:
                print("Detected: Full name screen")
                return "full_name"
        except:
            pass

        # Check for birthday screen
        try:
            picker_wheels = driver.find_elements(By.XPATH, "//XCUIElementTypePickerWheel")
            if len(picker_wheels) >= 3 or "birthday" in page_source.lower():
                print("Detected: Birthday screen")
                return "birthday"
        except:
            pass

        # Check for password screen
        try:
            password_field = driver.find_element(By.XPATH, '//*[@label="Password"]')
            if password_field:
                print("Detected: Password screen")
                return "password"
        except:
            pass

        # Check for save login screen
        try:
            not_now = driver.find_element(By.XPATH, '//*[contains(@label,"Not") and contains(@label,"now")]')
            if "save" in page_source.lower() or "login" in page_source.lower():
                print("Detected: Save login screen")
                return "save_login"
        except:
            pass

        # Check for mobile number screen
        try:
            mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @name="Mobile Number"]')
            if mobile_field:
                print("Detected: Mobile number screen")
                return "mobile"
        except:
            pass

        # Check for confirmation code screen
        if "confirmation code" in page_source.lower() or "enter the code" in page_source.lower():
            print("Detected: Confirmation code screen")
            return "confirmation_code"

        print("Could not detect current step")
        return None

    except Exception as e:
        print(f"Error detecting current step: {e}")
        return None


def createAccount(key):
    print("Creating account..")
    thename = "Maddie"  # Always use "Maddie" as the full name
    # Generate password with letters, numbers, and special characters
    allowed_chars = string.ascii_letters + string.digits + "!@$%^&*()-_=+"
    accpw = password_generator.generate(length=random.randint(9, 12), chars=allowed_chars)

    # First, check which screen we're on and navigate to account creation
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # Check if we're on the "Join Instagram" welcome screen
            get_started_button = driver.find_element(By.XPATH, '//*[@label="Get started"]')
            if get_started_button.is_enabled():
                get_started_button.click()
                print(f"Clicked 'Get started' button (Attempt {attempt + 1})")
                random_delay(2, 4)
                break
        except:
            # Not on "Join Instagram" screen, try to find "Create new account" button
            try:
                create_account_button = driver.find_element(By.XPATH, '//*[@label="Create new account"]')
                if create_account_button.is_enabled():
                    create_account_button.click()
                    print(f"Clicked on 'Create new account' (Attempt {attempt + 1})")

                    # Wait and verify we moved to next screen (mobile number or email screen)
                    print("Verifying page transition after clicking Create new account...")
                    page_changed = False
                    for verify_attempt in range(5):  # Check for 5 seconds
                        time.sleep(1)
                        try:
                            # Check if we're on mobile number or email screen
                            driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number" or @label="Email address" or @label="Email"]')
                            print(f"✓ Page transitioned to signup screen after {verify_attempt + 1} seconds")
                            page_changed = True
                            break
                        except:
                            # Also check for "Continue creating account" button
                            try:
                                driver.find_element(By.XPATH, '//*[@label="Continue creating account"]')
                                print(f"✓ 'Continue creating account' screen appeared after {verify_attempt + 1} seconds")
                                page_changed = True
                                break
                            except:
                                if verify_attempt < 4:
                                    print(f"Still on same page... ({verify_attempt + 1}/5)")

                    if page_changed:
                        print("Successfully moved to next screen")
                        break
                    else:
                        print(f"⚠️  Page didn't change after clicking - button click may have failed")
                        # Continue to retry
                else:
                    print(f"'Create new account' button found but not enabled (Attempt {attempt + 1})")
            except Exception as e:
                print(f"Error finding account creation buttons (Attempt {attempt + 1}): {str(e)}")

        if attempt < max_attempts - 1:
            print("Waiting before next attempt...")
            random_delay(2, 4)
    else:
        print("Failed to find account creation buttons after 3 attempts")
        return False

    try:
        driver.find_element(By.XPATH, '//*[@label="Continue creating account"]').click()
        print("Clicked 'Continue creating account'")
        # Wait for page to load
        print("Waiting for page to load after 'Continue creating account'...")
        time.sleep(5)
    except:
        print("'Continue creating account' button not found, proceeding...")

    # Check if Instagram is asking for email instead of mobile number
    print("Checking if on email signup screen...")
    for check_attempt in range(3):
        try:
            # Look for "Sign up with mobile number" button
            mobile_signup_button = driver.find_element(By.XPATH, '//*[@label="Sign up with mobile number"]')
            if mobile_signup_button.is_displayed():
                print("Email signup screen detected. Clicking 'Sign up with mobile number'...")
                mobile_signup_button.click()
                print("Switched to mobile number signup")
                time.sleep(2)
                break
        except:
            # Button not found - either we're already on mobile number screen or still loading
            try:
                # Check if we're already on mobile number screen
                mobile_field = driver.find_element(By.XPATH, '//*[@label="Mobile number" or @label="Mobile Number"]')
                if mobile_field:
                    print("Already on mobile number screen, proceeding...")
                    break
            except:
                if check_attempt < 2:
                    print(f"Neither email nor mobile screen found yet, waiting... (attempt {check_attempt + 1}/3)")
                    time.sleep(2)
                else:
                    print("Could not determine signup method, proceeding with flow...")

    # Fixed step order - only detect if step fails
    real_username = None

    # Expected step order (most common flow)
    expected_steps = [
        ("mobile", lambda: mobileNumber(key)),
        ("password", lambda: password(accpw)),
        ("birthday", birthday),
        ("full_name", lambda: fullName(thename)),
        ("username", doUsername),
        ("agree", agree),
        ("profile_picture", lambda: skip_profile_picture()),
    ]

    # Required steps that MUST be completed
    required_steps = {"mobile", "password", "birthday", "full_name", "username", "agree"}

    # Optional steps that may or may not appear
    optional_step_functions = {
        "save_login": save_login,
    }

    # Track which steps have been completed
    completed_steps = set()

    current_step_index = 0
    max_retry_per_step = 3
    instagram_already_restarted = False  # Track if we already restarted Instagram

    while current_step_index < len(expected_steps):
        step_name, step_function = expected_steps[current_step_index]
        print(f"\n--- Step {current_step_index + 1}/{len(expected_steps)}: {step_name} ---")

        retry_count = 0
        step_completed = False

        while retry_count < max_retry_per_step and not step_completed:
            try:
                # Try to execute the expected step with timeout
                print(f"Attempting {step_name} (attempt {retry_count + 1}/{max_retry_per_step})...")

                # Quick check: if we've tried twice and step keeps failing, detect what's actually there
                if retry_count >= 1:
                    print(f"Step {step_name} failed on previous attempt. Quick detection check...")
                    detected = detect_current_step()

                    # If still on the same step, it means the Next button click failed - retry same step
                    if detected == step_name:
                        print(f"✓ Still on {step_name} screen - retrying same step (Next button may have failed)")
                        # Continue to retry the same step - don't raise exception
                    elif detected and detected != step_name and detected != "complete":
                        print(f"⚠️  Instagram changed order! Expected '{step_name}' but found '{detected}'")
                        # Handle the detected step instead
                        raise Exception(f"Step order changed - on {detected} instead of {step_name}")

                result = step_function()

                if step_name == "username" and result:
                    real_username = result

                if result == "restart":
                    print(f"Step {step_name} requested restart")
                    return "restart"

                if result == "human_verification_failed":
                    print(f"\n{'='*60}")
                    print(f"❌ HUMAN VERIFICATION DETECTED - Account flagged by Instagram")
                    print(f"This account cannot be used - failing immediately")
                    print(f"{'='*60}\n")
                    return "human_verification"  # Return distinct value for tracking

                if result == False:
                    # Special handling for mobile step with single number strategy
                    if step_name == "mobile" and PHONE_NUMBER_STRATEGY == 'single':
                        print(f"Mobile step failed with single number strategy - restarting entire account creation")
                        return False  # Immediately restart account creation, don't retry step

                    print(f"Step {step_name} failed, retrying...")
                    retry_count += 1

                    # After first failure, do quick detection before retrying
                    if retry_count < max_retry_per_step:
                        print("Quick detection before retry...")
                        time.sleep(2)
                    continue

                # Step succeeded
                print(f"✓ Step '{step_name}' completed successfully")

                # Wait for Instagram to load next page before proceeding
                print("Waiting for next page to load...")
                time.sleep(3)  # Give Instagram time to transition to next step

                # Verify we actually moved off this screen (Next button might have failed)
                # Skip extended verification for agree step - it handles its own retry
                print(f"Verifying we moved off {step_name} screen...")
                still_on_same_screen = False

                if step_name == "agree":
                    # Agree step handles its own retry, just do a quick check
                    try:
                        detected_after = detect_current_step()
                        if detected_after == step_name:
                            print(f"⚠️  Still on {step_name} screen - will retry")
                            still_on_same_screen = True
                        else:
                            print(f"✓ Successfully moved off {step_name} screen (now on: {detected_after})")
                    except:
                        pass
                else:
                    # For other steps, do the full 15-second verification
                    for verify_check in range(3):  # Check 3 times over 15 seconds total
                        try:
                            detected_after = detect_current_step()
                            if detected_after == step_name:
                                if verify_check < 2:
                                    print(f"Still on {step_name} screen (check {verify_check + 1}/3), waiting 5 more seconds...")
                                    time.sleep(5)
                                    continue
                                else:
                                    print(f"⚠️  Still on {step_name} screen after 15 seconds - Next button click likely failed")
                                    still_on_same_screen = True
                                    break
                            else:
                                print(f"✓ Successfully moved off {step_name} screen (now on: {detected_after})")
                                break
                        except:
                            # Detection failed, assume we moved on
                            break

                # If still on same screen, just retry clicking Next button (don't retype everything)
                if still_on_same_screen:
                    print(f"Page didn't transition - retrying Next button click...")

                    # Just click Next button again without retyping
                    try:
                        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                        if next_button.is_enabled():
                            next_button.click()
                            print(f"Clicked Next button again (retry without retyping)")
                            time.sleep(3)

                            # Check if page transitioned this time
                            detected_after_retry = detect_current_step()
                            if detected_after_retry != step_name:
                                print(f"✓ Page transitioned after Next retry (now on: {detected_after_retry})")
                                # Successfully completed after Next retry
                                completed_steps.add(step_name)
                                step_completed = True
                                # Don't continue the loop, we're done with this step
                            else:
                                print(f"⚠️  Still on {step_name} after Next retry - will retry full step")
                                retry_count += 1
                                if retry_count < max_retry_per_step:
                                    continue
                                else:
                                    print(f"❌ Failed to complete {step_name} after {max_retry_per_step} attempts")
                                    step_completed = False
                                    break
                        else:
                            print("Next button not enabled - retrying full step")
                            retry_count += 1
                            if retry_count < max_retry_per_step:
                                continue
                            else:
                                step_completed = False
                                break
                    except Exception as e:
                        print(f"Error clicking Next button: {e} - retrying full step")
                        retry_count += 1
                        if retry_count < max_retry_per_step:
                            continue
                        else:
                            step_completed = False
                            break
                else:
                    # Successfully completed and moved to next screen
                    completed_steps.add(step_name)  # Track that this step is done
                    step_completed = True

            except Exception as e:
                # Step failed - check if we're on a different screen
                print(f"Error executing {step_name}: {str(e)}")
                print("Detecting actual current step to see if order changed...")

                detected_step = detect_current_step()
                if detected_step == "complete":
                    print("Account creation detected as complete!")
                    current_step_index = len(expected_steps)  # Exit loop
                    step_completed = True
                    break
                elif detected_step and detected_step != step_name:
                    # We're on a different step - Instagram changed the order or skipped a step
                    print(f"Detected we're actually on step: {detected_step}")

                    # Check if it's an optional step
                    if detected_step in optional_step_functions:
                        print(f"Executing optional step: {detected_step}")
                        try:
                            optional_result = optional_step_functions[detected_step]()
                            if optional_result != False:
                                print(f"✓ Optional step '{detected_step}' completed")
                                time.sleep(1)
                                # Try current expected step again
                                continue
                        except:
                            pass

                    # Check if we skipped ahead
                    for future_idx in range(current_step_index + 1, len(expected_steps)):
                        if expected_steps[future_idx][0] == detected_step:
                            print(f"Instagram skipped ahead to step {future_idx + 1}. Adjusting...")
                            current_step_index = future_idx - 1  # Will increment at end of loop
                            step_completed = True
                            # Mark the current step as skipped (not completed)
                            break

                    if not step_completed:
                        print(f"Could not match detected step '{detected_step}' to expected order")
                        retry_count += 1
                        time.sleep(2)
                else:
                    retry_count += 1
                    time.sleep(2)

        if not step_completed:
            print(f"Failed to complete step '{step_name}' after {max_retry_per_step} attempts")

            # Special handling for profile_picture step (optional and usually last)
            if step_name == "profile_picture":
                print("Profile picture step failed, but this is optional.")
                print("Closing and reopening Instagram to dismiss the prompt...")
                try:
                    driver.terminate_app("com.burbn.instagram")
                    time.sleep(2)
                    driver.activate_app("com.burbn.instagram")
                    time.sleep(3)
                    print("Instagram restarted - profile picture prompt dismissed")
                    print("✓ Profile picture step bypassed (optional)")
                    instagram_already_restarted = True  # Mark that we already restarted
                    # Don't set step_completed, just break to continue to next step
                except Exception as restart_err:
                    print(f"Failed to restart Instagram: {restart_err}")
                    print("Continuing anyway - profile picture is optional")

            # Try to detect what's happening
            detected_step = detect_current_step()
            if detected_step == "complete":
                print("Account creation detected as complete despite step failure!")
                break
            elif detected_step:
                print(f"Currently on: {detected_step}. May need manual intervention.")

            # If not profile_picture, this is a real failure
            if step_name != "profile_picture":
                return False
            else:
                # Profile picture is optional, continue anyway
                print("Continuing despite profile_picture failure (optional step)")

        current_step_index += 1

    # Verify all REQUIRED steps are actually completed
    missing_steps = required_steps - completed_steps
    if missing_steps:
        print(f"\n⚠️  Missing required steps: {missing_steps}")
        print("Using detection to find and complete missing steps...")

        max_missing_step_attempts = 10
        attempts = 0

        while missing_steps and attempts < max_missing_step_attempts:
            attempts += 1
            print(f"\nAttempt {attempts}/{max_missing_step_attempts} to complete missing steps...")

            detected = detect_current_step()
            print(f"Detected current step: {detected}")

            if detected == "complete":
                print("Account creation detected as complete!")
                break
            elif detected in missing_steps:
                print(f"Found missing step '{detected}' on screen. Executing...")
                try:
                    # Find the step function from expected_steps
                    step_func = None
                    for step_name, func in expected_steps:
                        if step_name == detected:
                            step_func = func
                            break

                    if step_func:
                        result = step_func()
                        if detected == "username" and result:
                            real_username = result

                        if result != False:
                            print(f"✓ Missing step '{detected}' completed!")
                            completed_steps.add(detected)
                            missing_steps = required_steps - completed_steps
                            time.sleep(2)
                        else:
                            print(f"Step '{detected}' failed")
                            time.sleep(2)
                    else:
                        print(f"Could not find function for step '{detected}'")
                        time.sleep(2)
                except Exception as e:
                    print(f"Error executing missing step '{detected}': {e}")
                    time.sleep(2)
            else:
                print(f"Detected step '{detected}' is not in missing steps. Waiting...")
                time.sleep(3)

        # Check again if all required steps are done
        missing_steps = required_steps - completed_steps
        if missing_steps:
            print(f"\n⚠️  Could not complete all required steps. Still missing: {missing_steps}")
            return False

    print("\n✓ All required steps completed!")
    print(f"Completed steps: {completed_steps}")
    print("Account creation completed successfully!")

    # Check for any final screens (Welcome, etc.)
    time.sleep(3)
    try:
        welcome_screen = driver.find_element(By.XPATH, '//*[contains(@label, "Welcome to") or contains(@label, "fun")]')
        if welcome_screen.is_displayed():
            print("Welcome screen detected, relaunching Instagram")
            driver.terminate_app("com.burbn.instagram")
            driver.activate_app("com.burbn.instagram")
            time.sleep(2)
    except:
        print("No welcome screen found, continuing...")

    # Only restart Instagram if we haven't already done so for profile picture bypass
    if not instagram_already_restarted:
        print("Closing and reopening Instagram...")
        driver.terminate_app("com.burbn.instagram")
        driver.activate_app("com.burbn.instagram")
        time.sleep(3)
    else:
        print("Instagram already restarted during profile picture bypass, skipping restart")

    # Wait 2 seconds before checking for popups to ensure they have time to appear
    time.sleep(2)

    # Handle notification popup (can be system alert OR Instagram in-app popup)
    print("Checking for notifications popup...")
    notifications_handled = False
    for attempt in range(4):  # Only 4 attempts = max 2 seconds
        print(f"  Notifications popup check attempt {attempt + 1}/4...")

        # First check for Instagram in-app "Not Now" popup (most common after reopen)
        # Using exact same XPath that works during link addition
        try:
            not_now_button = driver.find_element(By.XPATH, '//*[@label="Not Now" or @label="Not now"]')
            not_now_button.click()
            print("✓ Clicked 'Not Now' on Instagram notifications popup")
            notifications_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 2: System alert "Don't Allow" button
            dont_allow_button = driver.find_element(By.XPATH, "//*[@label=\"Don't Allow\"]")
            dont_allow_button.click()
            print("✓ Clicked 'Don't Allow' on notifications popup")
            notifications_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        if attempt < 3:
            time.sleep(0.5)

    if not notifications_handled:
        print("No notifications popup found")

    # Handle cookies popup (second popup that can appear)
    print("Checking for cookies popup...")
    cookies_handled = False
    for attempt in range(4):  # Only 4 attempts = max 2 seconds
        print(f"  Cookies popup check attempt {attempt + 1}/4...")

        try:
            # Method 1: Any element with exact "Allow all cookies" label
            allow_cookies_button = driver.find_element(By.XPATH, "//*[@label=\"Allow all cookies\"]")
            allow_cookies_button.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 1: Any element)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 2: Button with exact match
            allow_cookies_button = driver.find_element(By.XPATH, "//XCUIElementTypeButton[@label=\"Allow all cookies\"]")
            allow_cookies_button.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 2: Button)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 3: Button containing "Allow" and "cookies"
            allow_cookies_button = driver.find_element(By.XPATH, "//XCUIElementTypeButton[contains(@label, \"Allow\") and contains(@label, \"cookies\")]")
            allow_cookies_button.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 3)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 4: Static text "Allow all cookies"
            allow_cookies_text = driver.find_element(By.XPATH, "//XCUIElementTypeStaticText[@label=\"Allow all cookies\"]")
            allow_cookies_text.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 4: StaticText)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 5: Using @name attribute
            allow_cookies_button = driver.find_element(By.XPATH, "//*[@name=\"Allow all cookies\"]")
            allow_cookies_button.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 5: name)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        try:
            # Method 6: Accessibility identifier
            allow_cookies_button = driver.find_element(By.ACCESSIBILITY_ID, "Allow all cookies")
            allow_cookies_button.click()
            print("✓ Clicked 'Allow all cookies' on cookies popup (Method 6: accessibility ID)")
            cookies_handled = True
            time.sleep(0.5)
            break
        except:
            pass

        if attempt < 3:
            time.sleep(0.5)

    if not cookies_handled:
        print("No cookies popup found")

    # Add OnlyFans link to profile
    print("Adding OnlyFans link to profile...")
    link_added = addOnlyFansLink()

    if not link_added:
        print("\n" + "="*60)
        print("❌ FAILED: OnlyFans link could not be added to profile")
        print("Account creation ABORTED - will restart process")
        print("="*60 + "\n")
        return False

    print("Terminating Instagram before token retrieval")
    driver.terminate_app("com.burbn.instagram")

    getTokens = ""  # Initialize getTokens
    token_retrieval_attempts = 5
    for attempt in range(token_retrieval_attempts):
        try:
            print(f"Token retrieval attempt {attempt + 1}")
            driver.activate_app("com.apple.mobilenotes")
            time.sleep(2)
            print("Notes app opened")

            # Try to create a new note
            try:
                new_note_button = driver.find_element(By.XPATH, '//*[@name="New note"]')
                new_note_button.click()
                print("Clicked 'New note'")
                time.sleep(1)
            except:
                try:
                    new_note_button = driver.find_element(By.XPATH, '//*[@name="New Note"]')
                    new_note_button.click()
                    print("Clicked 'New Note'")
                    time.sleep(1)
                except:
                    print("New note button not found, assuming we're already in a note")

            # Find the text field and click to activate it
            try:
                # Try to find the text view (the main editable area)
                text_view = driver.find_element(By.XPATH, '//XCUIElementTypeTextView')
                text_view.click()
                print("Clicked on text view to activate")
                time.sleep(1)
            except:
                print("Text view not found, trying to tap on screen")
                # Tap in the middle of the screen to activate text field
                driver.execute_script("mobile: tap", {"x": 200, "y": 400})
                time.sleep(1)

            # Now paste the token (it's already in clipboard)
            try:
                # Method 1: Try to find and click the Paste button from the menu
                paste_button = driver.find_element(By.XPATH, '//*[@name="Paste"]')
                paste_button.click()
                print("Clicked 'Paste' button")
            except:
                # Method 2: Use keyboard shortcut to paste (Cmd+V)
                print("Paste button not found, trying to long press to show paste menu")
                driver.execute_script("mobile: tap", {"x": 200, "y": 400, "duration": 1.5})
                time.sleep(1)
                try:
                    paste_button = driver.find_element(By.XPATH, '//*[@name="Paste"]')
                    paste_button.click()
                    print("Clicked 'Paste' after long press")
                except:
                    print("Could not find Paste option")

            time.sleep(2)

            # Try to get the pasted text
            try:
                text_view = driver.find_element(By.XPATH, '//XCUIElementTypeTextView')
                getTokens = str(text_view.get_attribute("value"))
                print(f"Tokens retrieved: {getTokens}")
            except:
                print("Could not retrieve text from text view")
                getTokens = ""

            driver.terminate_app("com.apple.mobilenotes")
            print("Notes app closed")

            if getTokens:  # Only break if we got some tokens
                break
        except Exception as e:
            print(f"Token retrieval attempt {attempt + 1} failed: {str(e)}")
            if attempt == token_retrieval_attempts - 1:
                print("Failed to retrieve tokens after multiple attempts")

    print(f"Account successfully made: {real_username}:{accpw}")
    try:
        with open("accounts.txt", "a") as f:
            f.write(f"{real_username}:{accpw}|||{getTokens}\n")
        print("Account details saved to accounts.txt")
        return True
    except Exception as e:
        print(f"Error saving account details: {str(e)}")
        return False


# Parse command line arguments
parser = argparse.ArgumentParser(description='Run Instagram bot on a specific device')
parser.add_argument('--device-index', type=int, required=True, help='Device index from devices.json')
parser.add_argument('--config', type=str, default='devices.json', help='Path to devices config file')
parser.add_argument('--api-key', type=str, help='DaisySMS API key (optional, will use default if not provided)')
parser.add_argument('--ip-mode', type=str, default='potatso', choices=['potatso', 'mobile_data'], help='IP rotation mode: potatso or mobile_data')
parser.add_argument('--phone-strategy', type=str, default='multiple', choices=['single', 'multiple'], help='Phone number strategy: single or multiple')
args = parser.parse_args()

# Update IP rotation mode from command line argument
IP_ROTATION_MODE = args.ip_mode
print(f"IP rotation mode: {IP_ROTATION_MODE}")

# Update phone number strategy from command line argument
PHONE_NUMBER_STRATEGY = args.phone_strategy
print(f"Phone number strategy: {PHONE_NUMBER_STRATEGY}")

# Load device configuration
print(f"Loading device config from {args.config}...")
with open(args.config, 'r') as f:
    config = json.load(f)

device_config = config['devices'][args.device_index]
shared_config = config['shared_config']

print(f"Starting bot for device: {device_config['name']} (UDID: {device_config['udid']})")


def report_stat(stat_type, phone_numbers=None, sms_requests=None):
    """Report a stat to the dashboard (successful, confirm_human, or failed)

    Args:
        stat_type: 'successful', 'confirm_human', or 'failed'
        phone_numbers: Number of phone numbers tried (for detailed stats)
        sms_requests: Number of SMS requests for the successful number (for detailed stats)
    """
    try:
        payload = {'type': stat_type}

        # Add detailed tracking if provided
        if phone_numbers is not None and sms_requests is not None:
            # Determine category based on priority:
            # 1. Multiple numbers takes precedence
            # 2. Second request if only one number but 2+ requests
            # 3. First request otherwise
            if phone_numbers >= 2:
                category = 'multiple_numbers'
            elif sms_requests >= 2:
                category = 'second_request'
            else:
                category = 'first_request'

            payload['category'] = category
            print(f"Category: {category} (numbers: {phone_numbers}, requests: {sms_requests})")

        response = requests.post(
            f"http://127.0.0.1:5000/api/device/{args.device_index}/stats/update",
            json=payload,
            timeout=2
        )
        if response.status_code == 200:
            print(f"Reported stat: {stat_type}")
    except Exception as e:
        # Don't fail if dashboard is not running
        pass

# Build desired capabilities from config
desired_caps = {
    "platformName": shared_config["platformName"],
    "automationName": shared_config["automationName"],
    "udid": device_config["udid"],
    "deviceName": device_config["name"],
    "updatedWDABundleID": shared_config.get("updatedWDABundleID", "com.kevin.WebDriverAgentRunner"),
    "newCommandTimeout": str(shared_config["newCommandTimeout"]),
    "showXcodeLog": shared_config.get("showXcodeLog", False),
    "useNewWDA": shared_config.get("useNewWDA", False),
    "noReset": shared_config.get("noReset", True),
    "wdaLocalPort": device_config["wda_local_port"],
    "webDriverAgentUrl": f"http://127.0.0.1:{device_config['wda_local_port']}",
    "systemPort": device_config["system_port"],
    "mjpegServerPort": device_config["mjpeg_port"]
}

# Add optional signing config if present (for manual signing)
if "xcodeOrgId" in shared_config:
    desired_caps["xcodeOrgId"] = shared_config["xcodeOrgId"]
if "xcodeSigningId" in shared_config:
    desired_caps["xcodeSigningId"] = shared_config["xcodeSigningId"]
if "allowProvisioningUpdates" in shared_config:
    desired_caps["allowProvisioningUpdates"] = shared_config["allowProvisioningUpdates"]
if "resultBundlePath" in shared_config:
    desired_caps["resultBundlePath"] = shared_config["resultBundlePath"]

print("starting...")

# Convert desired_caps to XCUITestOptions
options = XCUITestOptions()
options.platform_name = desired_caps["platformName"]
options.automation_name = desired_caps["automationName"]
options.udid = desired_caps["udid"]
options.device_name = desired_caps["deviceName"]
options.new_command_timeout = int(desired_caps["newCommandTimeout"])
options.show_xcode_log = desired_caps["showXcodeLog"]
options.use_new_wda = desired_caps["useNewWDA"]
options.no_reset = desired_caps["noReset"]
options.set_capability("updatedWDABundleID", desired_caps["updatedWDABundleID"])
options.set_capability("wdaLocalPort", desired_caps["wdaLocalPort"])
options.set_capability("webDriverAgentUrl", desired_caps["webDriverAgentUrl"])
options.set_capability("systemPort", desired_caps["systemPort"])
options.set_capability("mjpegServerPort", desired_caps["mjpegServerPort"])

# Set optional capabilities if present
if "xcodeOrgId" in desired_caps:
    options.set_capability("xcodeOrgId", desired_caps["xcodeOrgId"])
if "xcodeSigningId" in desired_caps:
    options.set_capability("xcodeSigningId", desired_caps["xcodeSigningId"])
if "allowProvisioningUpdates" in desired_caps:
    options.set_capability("allowProvisioningUpdates", desired_caps["allowProvisioningUpdates"])
if "resultBundlePath" in desired_caps:
    options.set_capability("resultBundlePath", desired_caps["resultBundlePath"])

# Build Appium server URL from device config
appium_url = f"http://localhost:{device_config['appium_port']}/wd/hub"

# Initial connection with retry logic
while True:
    try:
        print(f"Attempting to connect to Appium at {appium_url}")
        print(f"Options type: {type(options)}")
        driver = webdriver.Remote(appium_url, options=options)
        print("Appium client connected")
        break
    except Exception as e:
        print(f"Connection failed: {str(e)}")
        traceback.print_exc()
        time.sleep(0.5)

print("Resetting IP and container (combined shortcut)")
crane()
print("Starting bot")

# Get API key from command line or use default
if args.api_key:
    key = args.api_key
    print(f"Using provided API key: {key}")
else:
    # Default values when not provided
    key = "rvBQZ3OgmbMp0O2lA7TcffH2dKQmsz"
    print(f"Using default API key: {key}")

# Run indefinitely - create accounts non-stop with WDA recovery
account_count = 0
successful_accounts = 0

while True:
    try:
        account_count += 1
        print(f"\n{'='*60}")
        print(f"Starting account creation #{account_count}")
        print(f"{'='*60}\n")

        # Reset phone number tracking for this account attempt (already global variables)
        phone_numbers_tried = 0
        sms_requests_for_current_number = 0

        # Check WDA health before starting
        if not check_wda_health():
            print("⚠️  WDA appears unhealthy, restarting...")
            restart_driver_session(options, device_config)

        # Account creation with WDA crash recovery
        wda_retry_count = 0
        max_wda_retries = 3
        account_created = False

        while wda_retry_count < max_wda_retries and not account_created:
            try:
                driver.activate_app("com.burbn.instagram")
                result = createAccount(key)

                # Check if WDA crash was detected and restart requested
                if result == "restart":
                    wda_retry_count += 1
                    print(f"\n⚠️  WDA crash detected in account creation (retry {wda_retry_count}/{max_wda_retries})")
                    if wda_retry_count < max_wda_retries:
                        restart_driver_session(options, device_config)
                        print("Retrying account creation after WDA restart...")
                        continue
                    else:
                        print("❌ Failed after maximum WDA recovery attempts")
                        raise Exception("Could not complete account creation after WDA restarts")

                # Check if human verification was triggered
                if result == "human_verification":
                    print(f"\n{'='*60}")
                    print(f"❌ Human verification detected - restarting process")
                    print(f"{'='*60}\n")
                    report_stat('confirm_human', phone_numbers_tried, sms_requests_for_current_number)
                    # Reset counters before retrying
                    phone_numbers_tried = 0
                    sms_requests_for_current_number = 0
                    # Reset IP and container (combined shortcut), then retry
                    crane()
                    continue  # Restart the account creation loop

                # Check if account creation failed
                if result == False:
                    print(f"\n{'='*60}")
                    print(f"❌ Account creation failed - restarting process")
                    print(f"{'='*60}\n")
                    report_stat('failed')
                    # Reset counters before retrying
                    phone_numbers_tried = 0
                    sms_requests_for_current_number = 0
                    # Reset IP and container (combined shortcut), then retry
                    crane()
                    continue  # Restart the account creation loop

                # Account created successfully
                crane()
                account_created = True
                successful_accounts += 1
                report_stat('successful', phone_numbers_tried, sms_requests_for_current_number)

                print(f"\n{'='*60}")
                print(f"✓ Successfully created account #{account_count}")
                print(f"Total successful: {successful_accounts}")
                print(f"{'='*60}\n")

            except Exception as e:
                if is_wda_crashed(e):
                    wda_retry_count += 1
                    print(f"\n⚠️  WDA crash during account creation (retry {wda_retry_count}/{max_wda_retries})")
                    if wda_retry_count < max_wda_retries:
                        restart_driver_session(options, device_config)
                        print("Retrying account creation after WDA restart...")
                    else:
                        print("❌ Failed after maximum WDA recovery attempts")
                        raise
                else:
                    # Not a WDA crash, re-raise the error
                    raise

    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("⏹️  Stopping bot - User interrupted with Ctrl+C")
        print(f"Total accounts attempted: {account_count}")
        print(f"Total successful accounts: {successful_accounts}")
        print("="*60)
        break

    except Exception as e:
        print(f"\n\n⚠️  Error during account creation #{account_count}: {e}")
        print("Continuing to next account...\n")

        # Try to recover gracefully
        try:
            # Check if it was a WDA crash that wasn't caught
            if is_wda_crashed(e):
                print("Detected uncaught WDA crash, restarting session...")
                restart_driver_session(options, device_config)

            crane()
        except Exception as recovery_error:
            print(f"Error during recovery: {recovery_error}")
            # Try one more WDA restart if recovery failed
            if is_wda_crashed(recovery_error):
                try:
                    restart_driver_session(options, device_config)
                except:
                    print("⚠️  Could not restart WDA, will try again next iteration")

print("\n" + "="*60)
print("Bot stopped")
print(f"Total accounts attempted: {account_count}")
print(f"Total successful accounts: {successful_accounts}")
print("="*60)

