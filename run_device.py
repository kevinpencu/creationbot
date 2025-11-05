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
           "connection refused" in error_str


def restart_driver_session(options):
    """Restart the Appium driver session after WDA crash"""
    global driver

    print("\n" + "="*60)
    print("⚠️  WDA CRASH DETECTED - Restarting driver session...")
    print("="*60)

    # Try to quit existing session
    try:
        if driver:
            driver.quit()
            print("✓ Closed old driver session")
    except:
        print("Old session already closed")

    # Wait for WDA to fully stop
    print("Waiting 5 seconds for WDA to clean up...")
    time.sleep(5)

    # Reconnect with retry logic
    max_retries = 5
    for attempt in range(max_retries):
        try:
            print(f"Reconnection attempt {attempt + 1}/{max_retries}...")
            driver = webdriver.Remote("http://localhost:6001/wd/hub", options=options)
            print("✓ Successfully reconnected to Appium!")
            print("="*60 + "\n")
            return driver
        except Exception as e:
            print(f"Reconnection failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # Exponential backoff
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
                    restart_driver_session(options)
                    time.sleep(2)  # Brief pause after restart
                else:
                    print(f"❌ Failed to execute {func.__name__} after {max_attempts} WDA recovery attempts")
                    raise
            else:
                # Not a WDA crash, re-raise the error
                raise


def generate_random_username():
    while True:
        username = fake.word() + fake.word()
        if not any(char.isdigit() for char in username):
            username += "".join(random.choices(string.digits, k=2))
        elif sum(char.isdigit() for char in username) == 1:
            username += random.choice(string.digits)
        if 12 <= len(username) <= 15:
            return username


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
        driver.execute_script("mobile: pressButton", {"name": "home"})
        time.sleep(0.5)  # Reduced from 1

        # Open Potatso by clicking on the app icon from home screen
        print("Looking for Potatso app on home screen...")
        driver.find_element(By.XPATH, '//*[@label="Potatso"]').click()
        time.sleep(0.8)  # Reduced from 2
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


def crane():
    print("Crane")
    try:
        driver.terminate_app("com.burbn.instagram")
        print("Instagram app terminated")
    except Exception as e:
        print(f"Error terminating Instagram: {e}")

    # Ensure we're on the home screen
    driver.execute_script("mobile: pressButton", {"name": "home"})
    time.sleep(2)
    print("Returned to home screen")

    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            # Locate the Instagram icon
            instagram = driver.find_element(By.XPATH, '//*[@label="Instagram"]')
            location = instagram.location
            size = instagram.size
            center_x = location['x'] + size['width'] / 2
            center_y = location['y'] + size['height'] / 2

            # Perform a long press
            print(f"Performing long press at: ({center_x}, {center_y})")
            driver.execute_script('mobile: touchAndHold', {
                'x': center_x,
                'y': center_y,
                'duration': 2
            })
            print("Long pressed on Instagram")

            # Click on Container
            container_option = driver.find_element(By.XPATH, '//*[contains(@label,"Container")]')
            container_option.click()
            print("Clicked on Container option")

            # Click on Settings
            settings_option = driver.find_element(By.XPATH, '(//*[@label="Settings"])[2]')
            settings_option.click()
            print("Clicked on Settings")

            # From here, proceed with creating a new container and deleting the old one
            add = driver.find_element(By.XPATH, '//*[@label="Add"]')
            add.click()

            fivedigit = randrange(10000, 99999)
            print(f"fivedigit: {fivedigit}")

            inputBox = driver.find_element(By.XPATH, '//*[@value="Name"]')
            addbot = driver.find_element(By.XPATH, '(//*[@label="Add"])[3]')
            inputBox.send_keys(str(fivedigit))
            addbot.click()
            print("Added new container")

            newcontainer = driver.find_element(By.XPATH, f'//*[@label="{fivedigit}"]')
            newcontainer.click()
            print("Clicked on new container")

            makedefault = driver.find_element(By.XPATH, '//*[@label="Make Default Container"]')
            makedefault.click()
            print("Set new container as default")

            # Navigate back and delete old container
            driver.find_element(By.XPATH, '//*[@label="Instagram"]').click()
            driver.find_element(By.XPATH, '//*[@label="Edit"]').click()
            print("Navigated back to edit containers")

            delete_attempts = 0
            while delete_attempts < 5:
                try:
                    delete = driver.find_element(By.XPATH, '//*[contains(@label,"Delete")]')
                    delete.click()
                    time.sleep(1)
                    confirm_delete = driver.find_element(By.XPATH, '//*[@label="Delete"]')
                    confirm_delete.click()
                    time.sleep(1)
                    final_delete = driver.find_element(By.XPATH, '//*[@label="Delete"]')
                    final_delete.click()
                    print("Deleted old container")
                    break
                except Exception as e:
                    print(f"Delete attempt {delete_attempts + 1} failed: {e}")
                    delete_attempts += 1
                    time.sleep(1)

            if delete_attempts == 5:
                print("Failed to delete old container after multiple attempts")

            # Close Settings and open Instagram
            driver.terminate_app("com.apple.Preferences")
            print("Crane operation completed successfully")
            return

        except Exception as e:
            print(f"Error during crane function (Attempt {attempt + 1}): {e}")
            if attempt < max_attempts - 1:
                print(f"Retrying... (Attempt {attempt + 1} of {max_attempts})")
                # Return to home screen before next attempt
                driver.execute_script("mobile: pressButton", {"name": "home"})
                time.sleep(2)
            else:
                print("Failed to complete crane operation after multiple attempts")
                return


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

    # Strategy 1: Try to find button by label text
    try:
        button = driver.find_element(By.XPATH, '//*[@label="I didn\'t get the code" or @label="I didn\'t get the code." or contains(@label, "didn\'t get")]')
        location = button.location
        print(f"✓ Found button by label at position ({location['x']}, {location['y']})")
        button.click()
        print("Clicked 'I didn't get the code' button (found by label)")
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
                    # Check if label contains relevant text
                    if label and ('code' in label.lower() or 'didn' in label.lower()):
                        print(f"✓ Found button by coordinates at ({location['x']}, {location['y']}) with label: '{label}'")
                        button.click()
                        print(f"Clicked 'I didn't get the code' button (found at position {location['x']}, {location['y']})")
                        return True
            except:
                continue
    except Exception as e:
        print(f"Error in coordinate-based search: {e}")

    # Strategy 3: Look for any button with text containing "code" on the left side
    try:
        buttons = driver.find_elements(By.XPATH, '//XCUIElementTypeButton')
        for button in buttons:
            try:
                label = button.get_attribute('label')
                location = button.location
                if label and 'code' in label.lower() and location['x'] < 150:
                    print(f"✓ Found button with 'code' in label at ({location['x']}, {location['y']}): '{label}'")
                    button.click()
                    print(f"Clicked button with 'code' in label: {label}")
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
    is_retry = False  # Track if we're retrying after a failed number

    while True:
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
                # Check if Instagram auto-detected wrong country (non-US)
                print("Checking for country code detection...")
                try:
                    # Look for country code text like "Estonia (+372)" or other non-US countries
                    # Common countries to check: Estonia, Latvia, Lithuania, Netherlands, etc.
                    country_keywords = ["Estonia", "Latvia", "Lithuania", "Netherlands", "Poland", "Finland",
                                        "Sweden", "Denmark", "Norway", "Germany", "France", "Spain", "Italy",
                                        "+372", "+371", "+370", "+31", "+48", "+358", "+46", "+45", "+47", "+49"]

                    # Search for any elements containing these country indicators
                    page_source = driver.page_source
                    country_detected = None
                    for keyword in country_keywords:
                        if keyword in page_source and keyword != "United States" and keyword != "+1":
                            country_detected = keyword
                            break

                    if country_detected:
                        print(f"WARNING: Non-US country detected: {country_detected}")
                        print("Raising exception to restart entire account creation process...")
                        raise Exception(f"Non-US country detected: {country_detected}. Restarting with new proxy.")
                    else:
                        print("No non-US country code detected. Proceeding with US number...")
                except Exception as e:
                    if "Non-US country detected" in str(e):
                        # Re-raise the country detection exception to trigger full restart
                        # This should propagate to the main loop
                        raise
                    else:
                        # Other exceptions during country check - just log and continue
                        print(f"Error checking country code: {e}")
                        print("Continuing anyway...")

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
                    # Use .clear() method like username (fast, instant clearing)
                    mobile_field.clear()
                    time.sleep(0.3)
                    print("Old number cleared")
                else:
                    print("First attempt - field should be empty")

                mobile_field.click()
                time.sleep(0.5)

                print("Entering new number...")
                mobile_field.send_keys("+" + number)  # Fast typing like password
                print(f"Entered phone number: +{number}")

                # Verify the correct number was entered
                time.sleep(0.5)
                final_value = mobile_field.get_attribute('value')
                print(f"Field now contains: '{final_value}'")

                random_delay(1, 3)  # Longer delay after entering the number

                next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                if next_button.is_enabled():
                    next_button.click()
                    print("Clicked Next after entering phone number")
                else:
                    print("Next button not enabled after entering phone number")
                    return False

                # Wait for loading to finish
                print("Waiting for Instagram to process phone number...")
                time.sleep(5)  # Initial wait for processing

                # Wait for Loading button to disappear (max 15 seconds)
                for _ in range(15):
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

                random_delay(2, 3)

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
                    print("Could not find confirmation code screen after waiting. Retrying with new number...")
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

                        # Click "Send code to SMS"
                        try:
                            send_sms_button = driver.find_element(By.XPATH, '//*[@label="Send code to SMS"]')
                            send_sms_button.click()
                            print("Clicked 'Send code to SMS' - WhatsApp redirect handled")
                            time.sleep(2)
                        except Exception as sms_err:
                            if is_wda_crashed(sms_err):
                                print("⚠️  WDA CRASH detected during 'Send code to SMS' click!")
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
                                # Check for all possible button labels
                                send_sms_button = driver.find_element(By.XPATH, '//*[@label="Send code to SMS" or @label="Resend code to SMS" or @label="Resend confirmation code"]')
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

                            # Try to click Next button if available, or check if page auto-advanced
                            try:
                                next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
                                if next_button.is_enabled():
                                    next_button.click()
                                    print("Clicked Next after entering code")
                                else:
                                    print("Next button not enabled, page may have auto-advanced")
                            except:
                                print("Next button not found, page likely auto-advanced")

                            # Wait for page transition to password screen
                            print("Waiting for page to transition to next step...")
                            time.sleep(3)

                            # Verify we've moved to the next page by checking for password field
                            for attempt in range(10):
                                try:
                                    password_field = driver.find_element(By.XPATH, '//*[@label="Password"]')
                                    if password_field:
                                        print("Successfully moved to password page")
                                        break
                                except:
                                    print(f"Waiting for password page (attempt {attempt + 1}/10)...")
                                    time.sleep(1)

                            break
                        else:
                            print("No text fields found for code entry")
                    except Exception as e:
                        print(f"Error entering confirmation code: {e}")
                else:
                    # No code received after 2 attempts, cancel old number and rent new one
                    print("No code received after 2 attempts. Cancelling old number and renting new one...")
                    cancelNumber(orderid, "daisy", key)

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
            # If this is a country detection exception, re-raise it to trigger full restart
            if "Non-US country detected" in str(e):
                print(f"Country detection exception caught in mobileNumber, re-raising...")
                raise

            print(f"Error in mobile number step: {str(e)}")
            try:
                print("Current page source:")
                print(driver.page_source)
            except:
                print("Unable to get page source")
            random_delay()
    return True


def password(accpw):
    password_field = driver.find_element(By.XPATH, '//*[@label="Password"]')
    password_field.click()
    time.sleep(0.3)
    password_field.send_keys(accpw)
    print(f"Entered password")
    time.sleep(1)  # Wait for Next button to become enabled

    # Click Next button ONCE and wait for page transition
    try:
        next_button = driver.find_element(By.XPATH, '//*[@label="Next"]')
        if next_button.is_enabled():
            next_button.click()
            print("Clicked Next after password")

            # Wait 2 seconds for page transition (Instagram needs time to process password)
            print("Waiting 2 seconds for page to transition...")
            time.sleep(2)

            # Verify we moved to next page (multiple checks for reliability)
            for check_attempt in range(3):
                try:
                    driver.find_element(By.XPATH, '//*[@label="Password"]')
                    # Password field still exists
                    if check_attempt < 2:
                        print(f"Password field still visible (check {check_attempt + 1}/3), waiting longer...")
                        time.sleep(2)
                        continue
                    else:
                        print("Password field still visible after all checks - page may not have transitioned")
                        # Don't return False - Instagram might have moved on anyway
                        # The step order system will detect the actual current page
                        return True
                except:
                    # Password field gone, we successfully moved to next page
                    print("Successfully moved to next page after password")
                    return True

            return True
        else:
            print("Next button not enabled")
            return False
    except Exception as e:
        print(f"Error clicking Next button: {e}")
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

    user = generate_random_username()

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
        next_click_attempts = 3
        for _ in range(next_click_attempts):
            if next_button.is_enabled():
                next_button.click()
                print("Clicked Next after username")
                random_delay(2, 4)

                # Check if we're still on the username page (indicating the username wasn't accepted)
                try:
                    driver.find_element(By.XPATH, '//*[@label="Username"]')
                    print("Still on username page. Username might not be available.")
                    # Try a new username
                    return doUsername()  # Recursive call with new username
                except:
                    print("Successfully moved past username page")
                    return user  # Successfully entered username and moved to next page
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

        # Wait longer for page to load after 'I agree' - it takes longer than other steps
        print("Waiting for page to load after 'I agree' (this takes longer than usual)...")
        time.sleep(15)  # Much longer wait - Instagram takes time to load profile picture screen

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


def addOnlyFansLink():
    """Add OnlyFans link to Instagram profile"""
    try:
        print("Adding OnlyFans link to profile...")

        # Click profile button (bottom right)
        max_attempts = 10
        profile_clicked = False
        for attempt in range(max_attempts):
            try:
                # Try to find profile button by looking for tab bar at bottom
                # Profile tab is usually the rightmost icon
                profile_button = driver.find_element(By.XPATH, '//*[@label="Profile"]')
                profile_button.click()
                print("Clicked profile button")
                profile_clicked = True
                time.sleep(2)
                break
            except:
                print(f"Profile button not found (attempt {attempt + 1}/{max_attempts}), waiting...")
                time.sleep(1)

        if not profile_clicked:
            print("Could not find profile button")
            return False

        # Click "Edit profile" button
        for attempt in range(5):
            try:
                edit_profile_button = driver.find_element(By.XPATH, '//*[@label="Edit profile"]')
                edit_profile_button.click()
                print("Clicked 'Edit profile'")
                time.sleep(2)
                break
            except:
                print(f"Edit profile button not found (attempt {attempt + 1}/5), waiting...")
                time.sleep(1)

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
        for attempt in range(5):
            try:
                links_button = driver.find_element(By.XPATH, '//*[@label="Links" or contains(@label, "Add links")]')
                links_button.click()
                print("Clicked 'Links'")
                time.sleep(2)
                break
            except:
                print(f"Links button not found (attempt {attempt + 1}/5), waiting...")
                time.sleep(1)

        # Click "Add external link"
        for attempt in range(5):
            try:
                add_external_link = driver.find_element(By.XPATH, '//*[@label="Add external link"]')
                add_external_link.click()
                print("Clicked 'Add external link'")
                time.sleep(2)
                break
            except:
                print(f"Add external link button not found (attempt {attempt + 1}/5), waiting...")
                time.sleep(1)

        # The URL field is already focused after clicking "Add external link"
        # Just type the OnlyFans link directly without clicking
        try:
            onlyfans_link = "onlyfans.com/uwumaddie/c46"

            # Find the text field and type directly
            text_field = driver.find_element(By.XPATH, '//XCUIElementTypeTextField')
            text_field.send_keys(onlyfans_link)  # Fast typing like password
            print(f"Entered OnlyFans link: {onlyfans_link}")
            time.sleep(1)
        except Exception as e:
            print(f"Error typing OnlyFans link: {e}")

        # Click "Done" button
        for attempt in range(5):
            try:
                done_button = driver.find_element(By.XPATH, '//*[@label="Done"]')
                done_button.click()
                print("Clicked 'Done'")
                time.sleep(2)
                break
            except:
                print(f"Done button not found (attempt {attempt + 1}/5), waiting...")
                time.sleep(1)

        # Navigate back to main screen (click back button or home)
        try:
            # Try to find back button to return to profile
            back_button = driver.find_element(By.XPATH, '//*[@label="Back"]')
            back_button.click()
            print("Navigated back from links screen")
            time.sleep(1)
        except:
            print("Back button not found, assuming already on profile")

        print("OnlyFans link successfully added to profile!")
        return True

    except Exception as e:
        print(f"Error adding OnlyFans link: {str(e)}")
        return False


def skip_profile_picture():
    """Skip the profile picture step"""
    try:
        skip_button = driver.find_element(By.XPATH, '//*[@label="Skip"]')
        skip_button.click()
        print("Clicked 'Skip' on profile picture screen")
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Error skipping profile picture: {e}")
        return False


def is_account_creation_complete():
    """Check if we've completed account creation and reached the main Instagram screen"""
    try:
        page_source = driver.page_source

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
                    random_delay(1, 3)
                    break
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
                    if detected and detected != step_name and detected != "complete":
                        print(f"⚠️  Instagram changed order! Expected '{step_name}' but found '{detected}'")
                        # Handle the detected step instead
                        raise Exception(f"Step order changed - on {detected} instead of {step_name}")

                result = step_function()

                if step_name == "username" and result:
                    real_username = result

                if result == "restart":
                    print(f"Step {step_name} requested restart")
                    return "restart"

                if result == False:
                    print(f"Step {step_name} failed, retrying...")
                    retry_count += 1

                    # After first failure, do quick detection before retrying
                    if retry_count < max_retry_per_step:
                        print("Quick detection before retry...")
                        time.sleep(2)
                    continue

                # Step succeeded
                print(f"✓ Step '{step_name}' completed successfully")
                completed_steps.add(step_name)  # Track that this step is done
                step_completed = True

                # Wait for Instagram to load next page before proceeding
                print("Waiting for next page to load...")
                time.sleep(2)  # Give Instagram time to transition to next step

            except Exception as e:
                # If this is a country detection exception, re-raise to trigger full restart
                if "Non-US country detected" in str(e):
                    print(f"Country detection exception in step {step_name}, propagating up...")
                    raise

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
        time.sleep(2)
    else:
        print("Instagram already restarted during profile picture bypass, skipping restart")

    # Handle notification popup
    for _ in range(20):
        try:
            not_now_button = driver.find_element(By.XPATH,
                                                 '//*[@label="Not Now" or @label="Not now" or @name="Not Now" or @name="Not now"]')
            not_now_button.click()
            print("Clicked 'Not Now' on notification popup")
            break
        except:
            pass

    # Add OnlyFans link to profile
    print("Adding OnlyFans link to profile...")
    addOnlyFansLink()

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
args = parser.parse_args()

# Load device configuration
print(f"Loading device config from {args.config}...")
with open(args.config, 'r') as f:
    config = json.load(f)

device_config = config['devices'][args.device_index]
shared_config = config['shared_config']

print(f"Starting bot for device: {device_config['name']} (UDID: {device_config['udid']})")

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

rotateIP()
print("Resetting container")
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
last_preventive_restart = 0

while True:
    try:
        account_count += 1
        print(f"\n{'='*60}")
        print(f"Starting account creation #{account_count}")
        print(f"{'='*60}\n")

        # Preventive restart every 5 successful accounts
        if successful_accounts - last_preventive_restart >= 5:
            print("\n" + "🔄 "*30)
            print(f"Preventive restart after {successful_accounts} successful accounts")
            print(f"This prevents WDA memory issues and keeps the bot stable")
            print("🔄 "*30 + "\n")
            restart_driver_session(options)
            last_preventive_restart = successful_accounts

        # Check WDA health before starting
        if not check_wda_health():
            print("⚠️  WDA appears unhealthy, restarting proactively...")
            restart_driver_session(options)

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
                        restart_driver_session(options)
                        print("Retrying account creation after WDA restart...")
                        continue
                    else:
                        print("❌ Failed after maximum WDA recovery attempts")
                        raise Exception("Could not complete account creation after WDA restarts")

                rotateIP()
                crane()
                account_created = True
                successful_accounts += 1

                print(f"\n{'='*60}")
                print(f"✓ Successfully created account #{account_count}")
                print(f"Total successful: {successful_accounts}")
                print(f"{'='*60}\n")

            except Exception as e:
                if is_wda_crashed(e):
                    wda_retry_count += 1
                    print(f"\n⚠️  WDA crash during account creation (retry {wda_retry_count}/{max_wda_retries})")
                    if wda_retry_count < max_wda_retries:
                        restart_driver_session(options)
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
                restart_driver_session(options)

            rotateIP()
            crane()
        except Exception as recovery_error:
            print(f"Error during recovery: {recovery_error}")
            # Try one more WDA restart if recovery failed
            if is_wda_crashed(recovery_error):
                try:
                    restart_driver_session(options)
                except:
                    print("⚠️  Could not restart WDA, will try again next iteration")

print("\n" + "="*60)
print("Bot stopped")
print(f"Total accounts attempted: {account_count}")
print(f"Total successful accounts: {successful_accounts}")
print("="*60)

