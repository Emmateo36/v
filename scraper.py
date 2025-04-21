# utils/scraper.py

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time
import json
import os
from utils.telegram import send_telegram_message
from utils.telegram import send_telegram_dev
from utils.storage import save_servers, load_servers, save_members
from config import TELEGRAM_CHAT_ID
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException
import random
from selenium.common.exceptions import StaleElementReferenceException
from datetime import datetime

from config import CHROME_USER_DATA_DIR
from config import ignored_names  
from config import same_count_limit
from config import MAX_SERVERS_TO_SCRAPE
from config import servername
from config import bot_id
from config import flag_keywords
from config import JOINED_AFTER_DATE


def create_driver_with_cookies():
    options = Options()
    #options.add_argument('--no-sandbox')        
    options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
    options.add_argument('--profile-directory=Default')
    driver = webdriver.Chrome(options=options)

    driver.get('https://discord.com/channels/@me')

    if os.path.exists("cookies.json"):
        with open("cookies.json", "r") as f:
            cookies = json.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
        driver.refresh()
        time.sleep(5)
    else:
        print("⚠️ cookies.json not found. Please login manually first.")
       # send_telegram_message("❗ Bot can't find cookies.json. Manual login required.")

    return driver






def fetch_server_list(driver, max_servers=MAX_SERVERS_TO_SCRAPE):
    time.sleep(8)
    servers = []
    visited = set()

    # Add more labels to ignore , "Direct Messages", "Home", "Friends"s

    try:
        server_icons = driver.find_elements(By.CSS_SELECTOR, 'nav [aria-label][tabindex]')
        print(f"🔍 Found {len(server_icons)} server icon elements.")

        for i, icon in enumerate(server_icons):
            try:
                # Re-fetch icons to avoid stale element issues
                server_icons = driver.find_elements(By.CSS_SELECTOR, 'nav [aria-label][tabindex]')

                if len(servers) >= max_servers:
                    break

                if icon in visited:
                    continue

                server_name = icon.get_attribute("aria-label") or "Unknown"

                if server_name in ignored_names:
                    print(f"⛔ Ignoring server/channel: {server_name}")
                    continue

                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", icon)
                time.sleep(1)

                icon.click()
                visited.add(icon)
                time.sleep(3)

                url = driver.current_url
                if "/channels/" in url:
                    parts = url.split("/")
                    if len(parts) >= 5:
                        server_id = parts[4]

                        servers.append({'id': server_id, 'name': server_name})
                        print(f"✅ Found server ID: {server_id} — {server_name}")
                else:
                    print("⚠️ Unexpected URL format:", url)
            except Exception as e:
                print("⚠️ Skipping icon due to error:", e)
                continue

        if servers:
            save_servers(servers)
            preview = "\n".join([f"{i+1}. {s['name']} ({s['id']})" for i, s in enumerate(servers)])
            send_telegram_dev(f"📥 Found and saved {len(servers)} servers:\n{preview}")
        else:
            send_telegram_dev(f"⚠️ No servers found for {bot_id}")

        return servers
    except Exception as e:
        send_telegram_dev(f"❌ Error fetching servers for {bot_id}:\n{str(e)}")
        return []






def load_existing_members(server_id):
    filepath = f"members/{server_id}.json"
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return []


def save_members(server_id, member_data):
    os.makedirs("members", exist_ok=True)
    filepath = f"members/{server_id}.json"
    with open(filepath, "w") as f:
        json.dump(member_data, f, indent=2)






def scrape_members_from_server(driver, server_id, server_name):
    try:
        url = f"https://discord.com/channels/{server_id}"
        driver.get(url)
        time.sleep(8)
        print(f"🌐 Navigated to: {url} — scraping now...")

        # ✅ Ensure members list is open
        try:
            print("📂 Checking if member list is visible...")
            toggle_button = driver.find_element(By.CSS_SELECTOR, '[aria-label="Show Member List"]')
            if toggle_button:
                print("🔓 Member list is collapsed. Expanding...")
                driver.execute_script("arguments[0].click();", toggle_button)
                time.sleep(2)
        except:
            print("✅ Member list is already open or toggle not needed.")

        scroll_box = driver.find_element(By.CSS_SELECTOR, "[class*=scrollerBase]")

        existing_members = load_existing_members(server_id)
        existing_usernames = set(m["username"] for m in existing_members)
        member_data = existing_members.copy()
        seen_usernames = existing_usernames.copy()
        
        new_added = 0
        skipped = 0
        same_count_times = 0
       
        scrolls = 0

        while same_count_times < same_count_limit:
            member_elements = driver.find_elements(By.CSS_SELECTOR, '[class*=member_]')
            print(f"🔁 Refetched {len(member_elements)} members...")

            i = 0
            while i < len(member_elements):
                try:
                    member = member_elements[i]
                    driver.execute_script("arguments[0].scrollIntoView(true);", member)
                    time.sleep(1)

                    display_name = member.get_attribute("innerText").split("\n")[0].strip()

                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", member)

                    print("🔍 Waiting for mini-profile username...")
                    WebDriverWait(driver, 4).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='userTagUsername']"))
                    )

                    username_element = driver.find_element(By.CSS_SELECTOR, "[class*='userTagUsername']")
                    username = username_element.text.strip()

                    #print(f"👤 Opening full profile for: {username}")
                    driver.execute_script("arguments[0].click();", username_element)
                    time.sleep(1.8)

                    print("⏳ Waiting for 'Member since' section...")
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//div[@aria-label='User Profile Modal']"))
                    )

                    discord_joined = ""
                    try:
                        member_since_div = driver.find_element(By.XPATH, "//div[@aria-label='User Profile Modal']//section[2]//div[2]")
                        discord_joined = member_since_div.text.strip()
                        #print(f"📅 Extracted join info: {discord_joined}")
                    except Exception as e:
                        print(f"❌ Failed to extract join info for {username}: {e}")

                    roles = []
                    try:
                        role_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'role')]")
                        for elem in role_elements:
                            role_text = elem.text.strip()
                            if role_text:
                                roles.append(role_text)
                    except Exception as e:
                        print(f"❌ Failed to get roles for {username}: {e}")

                    should_flag = False
                    for date_str in discord_joined.split("\n"):
                        try:
                            parsed_date = datetime.strptime(date_str.strip(), "%b %d, %Y")
                            
                            if parsed_date > JOINED_AFTER_DATE:
                                 # Check if any bad keyword is in username or display name
                                name_combined = (username + " " + display_name).lower()
                                if not any(keyword in name_combined for keyword in flag_keywords):
                                    should_flag = True
                                    break  # No need to check other dates
                                
                        except Exception as e:
                            print(f"⚠️ Couldn't parse date `{date_str}` for {username}: {e}")

                    member_obj = {
                        "display_name": display_name,
                        "username": username,
                        "added": should_flag,
                        "server_name": server_name,
                        "discord_joined": discord_joined,
                        "roles": roles
                    }

                    if username and username not in seen_usernames:
                        member_data.append(member_obj)
                        seen_usernames.add(username)
                        new_added += 1
                        save_members(server_id, member_data)
                        print(f"✅ Auto-saved {len(member_data)} members...")

                        if should_flag:
                            print(f"📨 Flagged and notifying: {username}")
                            safe_username = username.replace("_", "\\_")
                            message = f"🆕 **New User**\n- Username: {safe_username} ({display_name})\n- Joined: {discord_joined}\n- Server: {server_name}\n- Roles: {', '.join(roles)}"
                            send_telegram_message(message)
                            with open("recent_matches.txt", "a") as log:
                                log.write(f"{message}\n\n")
                    else:
                        print(f"⏩ Skipping b seen or empty uname. Dn: {display_name}")
                        skipped += 1


                    time.sleep(0.6)
                    i += 1

                except StaleElementReferenceException:
                    print(f"♻️ Skipping stale element at index {i}")
                    i += 1
                    continue

                except Exception as e:
                    error_message = f"⚠️ Error scraping member in `{server_name}`: {str(e)}"
                    print(error_message)
                    #send_telegram_message(error_message)
                    i += 1
                    continue

            scroll_top_before = driver.execute_script("return arguments[0].scrollTop", scroll_box)
            driver.execute_script("arguments[0].scrollTop += 1000;", scroll_box)
            time.sleep(random.uniform(2, 3))
            scroll_top_after = driver.execute_script("return arguments[0].scrollTop", scroll_box)

            if scroll_top_before == scroll_top_after:
                same_count_times += 1
            else:
                same_count_times = 0
                scrolls += 1

            if scrolls % 5 == 0:
                print("⏸️ Cooldown to let Discord load more...")
                time.sleep(4)

        save_members(server_id, member_data)
        send_telegram_dev(
            f"✅ Scraped `{new_added}` new users from `{server_name}`.\n🧾 Total: {len(member_data)} members\n🌀 Skipped: {skipped}"
        )

    except Exception as e:
        send_telegram_dev(f"❌ Error scraping server `{server_name}`:\n{str(e)}")
