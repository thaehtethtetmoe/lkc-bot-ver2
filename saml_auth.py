import requests
import re
import time

BASE_URL = "https://ntu.elentra.cloud"


def elentra_saml_login(msal_token_result):
    """
    Use Microsoft session cookies from MSAL to complete
    Elentra Institutional Login via Playwright.
    No password needed — reuses existing MS session.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Exception("PLAYWRIGHT_NOT_INSTALLED")

    # Extract MS session cookies from token result
    # MSAL stores session info we can inject into Playwright
    claims = msal_token_result.get("id_token_claims", {})
    ms_username = claims.get("preferred_username", "")
    print(f"[SAML] Attempting SSO for {ms_username}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            # Step 1: Hit Elentra SSO URL — this redirects to Microsoft
            print("[SAML] Step 1: Hitting Elentra SSO URL...")
            page.goto(
                f"{BASE_URL}/?action=ssologin&url=%2F",
                timeout=30000,
                wait_until="networkidle"
            )

            current_url = page.url
            print(f"[SAML] After SSO hit, landed on: {current_url[:80]}")

            # Step 2: If on Microsoft login page, try to pick account
            if "login.microsoftonline.com" in current_url or \
               "login.microsoft.com" in current_url:
                print("[SAML] On Microsoft — looking for account picker...")

                # Check for account picker (shows if MS has remembered accounts)
                try:
                    # Account picker tile
                    page.wait_for_selector(
                        f'[data-test-id="{ms_username}"]',
                        timeout=5000
                    )
                    page.click(f'[data-test-id="{ms_username}"]')
                    print(f"[SAML] Clicked account: {ms_username}")
                except Exception:
                    # No account picker — MS needs fresh login
                    print("[SAML] No account picker found")
                    # Try clicking any available account tile
                    try:
                        page.wait_for_selector('.tile', timeout=3000)
                        page.click('.tile')
                        print("[SAML] Clicked first account tile")
                    except Exception:
                        print("[SAML] No tiles found — MS needs password")
                        raise Exception("SAML_NEEDS_PASSWORD")

                # Wait for redirect back to Elentra
                print("[SAML] Waiting for redirect back to Elentra...")
                page.wait_for_url("**/ntu.elentra.cloud/**", timeout=20000)

            # Step 3: Check if we landed on Elentra
            current_url = page.url
            print(f"[SAML] Final URL: {current_url[:80]}")

            if "ntu.elentra.cloud" not in current_url:
                page.screenshot(path="/tmp/saml_debug.png")
                raise Exception(f"SAML_WRONG_PAGE: {current_url[:80]}")

            # Step 4: Extract JWT
            content = page.content()
            jwt_match = re.search(r"var JWT\s*=\s*'([^']+)'", content)
            if not jwt_match:
                page.screenshot(path="/tmp/saml_debug.png")
                print(f"[SAML] Page title: {page.title()}")
                raise Exception("SAML_NO_JWT")

            jwt_token = jwt_match.group(1)
            print("[SAML] ✅ JWT extracted!")

            # Step 5: Transfer cookies to requests.Session
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": BASE_URL
            })

            all_cookies = context.cookies()
            for cookie in all_cookies:
                domain = cookie.get("domain", "")
                if "elentra" in domain or "ntu.edu.sg" in domain:
                    session.cookies.set(
                        cookie["name"],
                        cookie["value"]
                    )
            print(f"[SAML] Transferred {len(all_cookies)} cookies")

            # Step 6: Verify session
            test = session.get(
                f"{BASE_URL}/api/events-calendar.api.php",
                params={
                    "dtype": "week",
                    "dstamp": int(time.time()),
                    "local_timezone": "Asia/Singapore",
                    "viewtype": "list",
                    "parentonly": "no",
                    "pv": "1"
                },
                timeout=10
            )
            data = test.json()
            if "events" not in data:
                raise Exception("SAML_SESSION_INVALID")

            print("[SAML] ✅ Elentra session verified!")
            return session, jwt_token

        finally:
            browser.close()


# Keep for compatibility
def elentra_sso_login_with_cookies(msal_token_result):
    return elentra_saml_login(msal_token_result)

# import requests
# import re
# import time
# import os

# BASE_URL = "https://ntu.elentra.cloud"
# PROFILES_DIR = "/home/site/wwwroot/browser_profiles"  # Azure persistent storage


# def get_profile_dir(username):
#     """Each user gets their own browser profile directory."""
#     safe_username = username.replace("@", "_").replace(".", "_")
#     profile_dir = os.path.join(PROFILES_DIR, safe_username)
#     os.makedirs(profile_dir, exist_ok=True)
#     return profile_dir


# def elentra_saml_login(msal_token_result):
#     """
#     Use persistent Playwright browser profile to complete Elentra SSO.
#     First time: MS login page appears → needs password (one time only).
#     After that: MS cookies saved → fully automatic.
#     """
#     try:
#         from playwright.sync_api import sync_playwright
#     except ImportError:
#         raise Exception("PLAYWRIGHT_NOT_INSTALLED")

#     claims = msal_token_result.get("id_token_claims", {})
#     ms_username = claims.get("preferred_username", "unknown")
#     print(f"[SAML] Starting persistent SSO for {ms_username}...")

#     profile_dir = get_profile_dir(ms_username)
#     print(f"[SAML] Using profile: {profile_dir}")

#     with sync_playwright() as p:
#         # Use persistent context — saves MS cookies between sessions
#         context = p.chromium.launch_persistent_context(
#             user_data_dir=profile_dir,
#             headless=True,
#             args=["--no-sandbox", "--disable-dev-shm-usage"],
#             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#         )

#         page = context.new_page()

#         try:
#             # Step 1: Hit Elentra SSO URL
#             print("[SAML] Step 1: Navigating to Elentra SSO...")
#             page.goto(
#                 f"{BASE_URL}/?action=ssologin&url=%2F",
#                 timeout=30000,
#                 wait_until="networkidle"
#             )

#             current_url = page.url
#             print(f"[SAML] Landed on: {current_url[:80]}")

#             # Step 2: Check where we are
#             if "ntu.elentra.cloud" in current_url:
#                 # Already logged in via saved cookies!
#                 print("[SAML] ✅ Already authenticated via saved profile!")

#             elif "login.microsoftonline.com" in current_url or \
#                  "login.microsoft.com" in current_url:
#                 print("[SAML] On Microsoft login — checking for saved account...")

#                 # Check if MS remembers the account (saved cookies)
#                 try:
#                     # Look for account picker
#                     page.wait_for_selector(
#                         '[data-test-id], .tile, [role="option"]',
#                         timeout=5000
#                     )
#                     print("[SAML] Account picker found — clicking account...")
                    
#                     # Try clicking the specific account
#                     try:
#                         page.click(f'[data-test-id="{ms_username}"]', timeout=3000)
#                     except Exception:
#                         # Click first available account
#                         page.click('.tile', timeout=3000)
                    
#                     print("[SAML] Account selected — waiting for Elentra...")
#                     page.wait_for_url("*ntu.elentra.cloud*", timeout=20000)

#                 except Exception:
#                     print("[SAML] No saved MS session — first time login needed")
#                     # Save screenshot for debugging
#                     try:
#                         page.screenshot(path="/tmp/saml_first_login.png")
#                     except Exception:
#                         pass
#                     raise Exception("SAML_FIRST_TIME_LOGIN_NEEDED")

#             else:
#                 page.screenshot(path="/tmp/saml_unknown.png")
#                 raise Exception(f"SAML_UNEXPECTED_PAGE: {current_url[:80]}")

#             # Step 3: Handle "Stay signed in?" if shown
#             try:
#                 stay_signed_in = page.wait_for_selector(
#                     '#idSIButton9, input[value="Yes"]',
#                     timeout=3000
#                 )
#                 if stay_signed_in:
#                     page.click('#idSIButton9')
#                     print("[SAML] Clicked 'Stay signed in'")
#                     page.wait_for_url("*ntu.elentra.cloud*", timeout=15000)
#             except Exception:
#                 pass

#             # Step 4: Verify we're on Elentra
#             current_url = page.url
#             if "ntu.elentra.cloud" not in current_url:
#                 raise Exception(f"SAML_NOT_ON_ELENTRA: {current_url[:80]}")

#             # Step 5: Extract JWT
#             content = page.content()
#             jwt_match = re.search(r"var JWT\s*=\s*'([^']+)'", content)
#             if not jwt_match:
#                 print(f"[SAML] Page title: {page.title()}")
#                 page.screenshot(path="/tmp/saml_no_jwt.png")
#                 raise Exception("SAML_NO_JWT")

#             jwt_token = jwt_match.group(1)
#             print("[SAML] ✅ JWT extracted!")

#             # Step 6: Transfer cookies to requests.Session
#             session = requests.Session()
#             session.headers.update({
#                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
#                 "Referer": BASE_URL
#             })

#             all_cookies = context.cookies()
#             transferred = 0
#             for cookie in all_cookies:
#                 domain = cookie.get("domain", "")
#                 if "elentra" in domain or "ntu.edu.sg" in domain:
#                     session.cookies.set(cookie["name"], cookie["value"])
#                     transferred += 1
#             print(f"[SAML] Transferred {transferred} Elentra cookies")

#             # Step 7: Verify session
#             test = session.get(
#                 f"{BASE_URL}/api/events-calendar.api.php",
#                 params={
#                     "dtype": "week",
#                     "dstamp": int(time.time()),
#                     "local_timezone": "Asia/Singapore",
#                     "viewtype": "list",
#                     "parentonly": "no",
#                     "pv": "1"
#                 },
#                 timeout=10
#             )
#             data = test.json()
#             if "events" not in data:
#                 raise Exception("SAML_SESSION_INVALID")

#             print("[SAML] ✅ Elentra session verified!")
#             return session, jwt_token

#         finally:
#             context.close()


# def elentra_sso_login_with_cookies(msal_token_result):
#     return elentra_saml_login(msal_token_result)

# #helper function 
# def _save_ms_session_via_playwright(msal_token_result, elentra_username, elentra_password):
#     """
#     After /link succeeds, run Playwright to complete the full SSO flow
#     and save MS cookies to the persistent profile for future auto-logins.
#     """
#     try:
#         from playwright.sync_api import sync_playwright
#     except ImportError:
#         return

#     claims = msal_token_result.get("id_token_claims", {})
#     ms_username = claims.get("preferred_username", elentra_username)
#     profile_dir = get_profile_dir(ms_username)

#     print(f"[SAML] Saving MS profile for {ms_username}...")

#     with sync_playwright() as p:
#         context = p.chromium.launch_persistent_context(
#             user_data_dir=profile_dir,
#             headless=True,
#             args=["--no-sandbox", "--disable-dev-shm-usage"],
#         )
#         page = context.new_page()

#         try:
#             page.goto(
#                 f"{BASE_URL}/?action=ssologin&url=%2F",
#                 timeout=30000,
#                 wait_until="networkidle"
#             )

#             current_url = page.url

#             if "login.microsoftonline.com" in current_url:
#                 # Fill MS login with known credentials
#                 try:
#                     page.wait_for_selector('input[type="email"]', timeout=10000)
#                     page.fill('input[type="email"]', ms_username)
#                     page.click('input[type="submit"]')

#                     page.wait_for_selector('input[type="password"]', timeout=10000)
#                     page.fill('input[type="password"]', elentra_password)
#                     page.click('input[type="submit"]')

#                     # Stay signed in
#                     try:
#                         page.click('#idSIButton9', timeout=5000)
#                     except Exception:
#                         pass

#                     page.wait_for_url("*ntu.elentra.cloud*", timeout=20000)
#                     print("[SAML] ✅ MS profile saved successfully!")
#                 except Exception as ex:
#                     print(f"[SAML] Profile save failed: {ex}")

#             elif "ntu.elentra.cloud" in current_url:
#                 print("[SAML] Already authenticated — profile already valid!")

#         finally:
#             context.close()