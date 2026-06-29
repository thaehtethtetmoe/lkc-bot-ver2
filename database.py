"""
database.py - Hybrid Storage Adapter with Encryption
Supports both JSON file and Azure Table Storage
"""

import os
import json
from datetime import datetime, timedelta
from threading import Lock
from cryptography.fernet import Fernet

# ── CONFIGURATION ──────────────────────────────────────────
STORAGE_TYPE = os.environ.get("STORAGE_TYPE", "json")

# ── ENCRYPTION SETUP ──────────────────────────────────────
ENCRYPTION_KEY = os.environ.get('STUDENT_CONFIG_KEY')

if ENCRYPTION_KEY:
    try:
        _cipher = Fernet(ENCRYPTION_KEY.encode())
        print("[DB] ✅ Encryption key loaded")
    except Exception as e:
        print(f"[DB] ⚠️ Invalid encryption key: {e}")
        _cipher = None
else:
    _cipher = None
    print("[DB] ⚠️ STUDENT_CONFIG_KEY not set — passwords will be stored in PLAIN TEXT")
    print("[DB] ℹ️  Generate a key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

def encrypt_password(password):
    """Encrypt password if encryption key is available."""
    if _cipher and password:
        try:
            return _cipher.encrypt(password.encode()).decode()
        except Exception as e:
            print(f"[DB] Encryption error: {e}")
            return password
    return password

def decrypt_password(password):
    """Decrypt password if encryption key is available."""
    if _cipher and password:
        try:
            return _cipher.decrypt(password.encode()).decode()
        except Exception:
            return password
    return password

# ── DATABASE PATH ─────────────────────────────────────────
DB_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_FILE = os.path.join(DB_DIR, "student_config.json")
print(f"[DB] Using database file: {DB_FILE}")

# ── IN-MEMORY CACHE ──────────────────────────────────────
_cache = {}
_cache_lock = Lock()
_cache_loaded = False

# ── AZURE TABLE STORAGE (optional) ──────────────────────
_table_client = None

def _init_azure_table():
    """Lazy initialization of Azure Table Storage."""
    global _table_client, STORAGE_TYPE
    
    if STORAGE_TYPE != "table":
        return False
    
    if _table_client is not None:
        return True
    
    try:
        from azure.data.tables import TableServiceClient
        
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            print("[DB] ⚠️ AZURE_STORAGE_CONNECTION_STRING not set, falling back to JSON")
            STORAGE_TYPE = "json"
            return False
        
        table_name = os.environ.get("TABLE_NAME", "students")
        service_client = TableServiceClient.from_connection_string(connection_string)
        _table_client = service_client.create_table_if_not_exists(table_name)
        print(f"[DB] ✅ Connected to Azure Table Storage (table: {table_name})")
        return True
        
    except ImportError:
        print("[DB] ⚠️ Azure SDK not installed, falling back to JSON")
        STORAGE_TYPE = "json"
        return False
    except Exception as e:
        print(f"[DB] ⚠️ Azure Table Storage error: {e}, falling back to JSON")
        STORAGE_TYPE = "json"
        return False

# ── JSON STORAGE FUNCTIONS ──────────────────────────────

def _load_json():
    """Load all data from JSON file."""
    if not os.path.exists(DB_FILE):
        return {}
    
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Decrypt passwords on load
            for username, user_data in data.items():
                if user_data.get("password"):
                    user_data["password"] = decrypt_password(user_data["password"])
            return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[DB] Error loading JSON: {e}")
        return {}

def _save_json(data):
    """Save all data to JSON file atomically with encryption."""
    try:
        os.makedirs(DB_DIR, exist_ok=True)
        
        # Encrypt passwords before saving
        data_to_save = {}
        for username, user_data in data.items():
            data_copy = dict(user_data)
            if data_copy.get("password"):
                data_copy["password"] = encrypt_password(data_copy["password"])
            data_to_save[username] = data_copy
        
        temp_file = DB_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, DB_FILE)
        print(f"[DB] ✅ Successfully saved to {DB_FILE}")
        return True
    except Exception as e:
        print(f"[DB] Error saving JSON: {e}")
        return False

# ── UNIFIED DATABASE INTERFACE ──────────────────────────

def _load_cache():
    """Load data from storage into cache."""
    global _cache, _cache_loaded
    
    with _cache_lock:
        if _cache_loaded:
            return
        
        # Try Azure Table first if configured
        if STORAGE_TYPE == "table" and _init_azure_table():
            try:
                entities = list(_table_client.query_entities(
                    query_filter="PartitionKey eq 'student'"
                ))
                for entity in entities:
                    username = entity.get("username") or entity.get("RowKey")
                    if username:
                        # Decrypt password when loading from Azure
                        encrypted_pw = entity.get("password", "")
                        _cache[username] = {
                            "username": username,
                            "password": decrypt_password(encrypted_pw),
                            "email": entity.get("email", ""),
                            "registered_at": entity.get("registered_at", ""),
                            "preferences": json.loads(entity.get("preferences", "{}")),
                            "bus_config": json.loads(entity.get("bus_config", "{}")),
                            "loa_rejection_notified": json.loads(entity.get("loa_rejection_notified", "[]")),
                            "updated_at": entity.get("updated_at", "")
                        }
                print(f"[DB] Loaded {len(_cache)} students from Azure Table")
                _cache_loaded = True
                return
            except Exception as e:
                print(f"[DB] Azure Table load failed: {e}, falling back to JSON")
        
        # Fallback to JSON
        data = _load_json()
        for username, user_data in data.items():
            _cache[username] = user_data
        _cache_loaded = True
        print(f"[DB] Loaded {len(_cache)} students from JSON")

def _force_load_cache():
    """
    Always re-read from persistent storage (JSON or Azure), ignoring the
    _cache_loaded flag.  Use this when you need a guaranteed fresh view —
    e.g. in a scheduler job that runs across gunicorn workers, where another
    worker may have written new data (like loa_rejection_notified) since
    this process last loaded its cache.
    """
    global _cache, _cache_loaded

    with _cache_lock:
        # Try Azure Table first if configured
        if STORAGE_TYPE == "table" and _init_azure_table():
            try:
                entities = list(_table_client.query_entities(
                    query_filter="PartitionKey eq 'student'"
                ))
                new_cache = {}
                for entity in entities:
                    username = entity.get("username") or entity.get("RowKey")
                    if username:
                        encrypted_pw = entity.get("password", "")
                        new_cache[username] = {
                            "username": username,
                            "password": decrypt_password(encrypted_pw),
                            "email": entity.get("email", ""),
                            "registered_at": entity.get("registered_at", ""),
                            "preferences": json.loads(entity.get("preferences", "{}")),
                            "bus_config": json.loads(entity.get("bus_config", "{}")),
                            "loa_rejection_notified": json.loads(entity.get("loa_rejection_notified", "[]")),
                            "updated_at": entity.get("updated_at", "")
                        }
                _cache = new_cache
                _cache_loaded = True
                print(f"[DB] Force-loaded {len(_cache)} students from Azure Table")
                return
            except Exception as e:
                print(f"[DB] Azure Table force-load failed: {e}, falling back to JSON")

        # Fallback to JSON
        data = _load_json()
        new_cache = {}
        for username, user_data in data.items():
            new_cache[username] = user_data
        _cache = new_cache
        _cache_loaded = True
        print(f"[DB] Force-loaded {len(_cache)} students from JSON")

def _save_to_json(username, data):
    """Save a single student to JSON file."""
    all_data = _load_json()
    all_data[username] = data
    return _save_json(all_data)

def _save_to_azure(username, data):
    """Save a single student to Azure Table Storage."""
    if STORAGE_TYPE != "table" or not _init_azure_table():
        return False
    
    try:
        # Encrypt password before saving to Azure
        encrypted_pw = encrypt_password(data.get("password", ""))
        
        entity = {
            "PartitionKey": "student",
            "RowKey": username,
            "username": username,
            "password": encrypted_pw,
            "email": data.get("email", ""),
            "registered_at": data.get("registered_at", ""),
            "preferences": json.dumps(data.get("preferences", {})),
            "bus_config": json.dumps(data.get("bus_config", {})),
            "loa_rejection_notified": json.dumps(data.get("loa_rejection_notified", [])),
            "updated_at": data.get("updated_at", datetime.now().isoformat())
        }
        _table_client.upsert_entity(entity)
        return True
    except Exception as e:
        print(f"[DB] Azure Table save error for {username}: {e}")
        return False

# ── PUBLIC INTERFACE ──────────────────────────────────────

def get_student_config(username):
    """Get all config for a student. Returns None if not found."""
    _load_cache()
    
    with _cache_lock:
        if username in _cache:
            return _cache[username].copy()
    
    return None

def get_all_reminder_students():
    """Get all students registered for reminders (have an email).
    Always force-reloads from persistent storage so that loa_rejection_notified
    (and any other fields written by other gunicorn workers or a previous
    scheduler run) are never stale in multi-worker deployments.
    """
    _force_load_cache()
    
    result = {}
    with _cache_lock:
        for username, data in _cache.items():
            if data.get("email"):
                result[username] = {
                    "password": data.get("password", ""),  # Already decrypted
                    "email": data.get("email", ""),
                    "preferences": data.get("preferences", {}),
                    "bus_config": data.get("bus_config", {}),
                    "loa_rejection_notified": data.get("loa_rejection_notified", [])
                }
    return result

def save_student_config(username, **kwargs):
    """Save student config. Creates or updates."""
    _load_cache()
    
    # Get existing data
    existing = {}
    with _cache_lock:
        if username in _cache:
            existing = _cache[username]
    
    # Merge with new data
    now = datetime.now().isoformat()
    data = {
        "username": username,
        "password": kwargs.get("password", existing.get("password", "")),
        "email": kwargs.get("email", existing.get("email", "")),
        "registered_at": existing.get("registered_at", now),
        "preferences": kwargs.get("preferences", existing.get("preferences", {})),
        "bus_config": kwargs.get("bus_config", existing.get("bus_config", {})),
        "loa_rejection_notified": kwargs.get("loa_rejection_notified", existing.get("loa_rejection_notified", [])),
        "updated_at": now
    }
    
    # Update cache
    with _cache_lock:
        _cache[username] = data
    
    # Save to JSON (always)
    success = _save_to_json(username, data)
    
    # Also save to Azure if available
    if STORAGE_TYPE == "table":
        azure_success = _save_to_azure(username, data)
        if azure_success:
            print(f"[DB] ✅ Saved {username} to Azure Table")
        else:
            print(f"[DB] ⚠️ Azure save failed for {username}, but JSON saved")
    
    return success

def delete_student_config(username):
    """Remove a student's config."""
    _load_cache()
    
    # Remove from cache
    with _cache_lock:
        if username in _cache:
            del _cache[username]
    
    # Remove from JSON
    all_data = _load_json()
    if username in all_data:
        del all_data[username]
        _save_json(all_data)
    
    # Remove from Azure
    if STORAGE_TYPE == "table" and _init_azure_table():
        try:
            _table_client.delete_entity(
                partition_key="student",
                row_key=username
            )
        except Exception as e:
            print(f"[DB] Azure delete error for {username}: {e}")
    
    print(f"[DB] Deleted config for {username}")
    return True

def restore_to_reminder_store(reminder_store):
    """Populate in-memory reminder_store from storage."""
    students = get_all_reminder_students()
    for username, data in students.items():
        reminder_store[username] = data
    print(f"[DB] Restored {len(reminder_store)} student(s) to reminder_store")

# ── SESSION CACHE IN AZURE TABLE ──────────────────────────
# Table name: "sessions" (separate from "students" table)
# PartitionKey: "session"
# RowKey: username
# Fields: session_cookies (JSON), jwt_token, expires_at (ISO timestamp)

_SESSION_TABLE_NAME = os.environ.get("SESSION_TABLE_NAME", "sessions")
_session_table_client = None

def _get_session_table_client():
    """Get table client for sessions table."""
    global _session_table_client
    
    if _session_table_client is not None:
        return _session_table_client
    
    if STORAGE_TYPE != "table":
        print("[SESSION DB] Not using Azure Table (STORAGE_TYPE != 'table')")
        return None
    
    if not _init_azure_table():
        print("[SESSION DB] Failed to initialize Azure Table")
        return None
    
    try:
        from azure.data.tables import TableServiceClient
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            print("[SESSION DB] No connection string")
            return None
        service_client = TableServiceClient.from_connection_string(connection_string)
        _session_table_client = service_client.create_table_if_not_exists(_SESSION_TABLE_NAME)
        print(f"[SESSION DB] ✅ Connected to session table: {_SESSION_TABLE_NAME}")
        return _session_table_client
    except Exception as e:
        print(f"[SESSION DB] Error: {e}")
        return None

def save_session(username: str, session_cookies: dict, jwt_token: str, ttl_seconds: int = 240):
    """
    Save an Elentra session to Azure Table Storage.
    session_cookies: dict of cookie name -> value from requests.Session
    jwt_token: string
    ttl_seconds: how long the session is valid (default 4 minutes)
    """
    try:
        table_client = _get_session_table_client()
        if not table_client:
            print(f"[SESSION DB] Cannot save {username} - no Azure Table")
            return False
        
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        
        # Serialize cookies as JSON
        cookies_json = json.dumps(session_cookies)
        
        entity = {
            "PartitionKey": "session",
            "RowKey": username,
            "username": username,
            "session_cookies": cookies_json,
            "jwt_token": jwt_token,
            "expires_at": expires_at,
            "updated_at": datetime.now().isoformat()
        }
        
        table_client.upsert_entity(entity)
        print(f"[SESSION DB] ✅ Saved session for {username}, expires at {expires_at}")
        return True
        
    except Exception as e:
        print(f"[SESSION DB] Save failed for {username}: {e}")
        return False

def get_session(username: str):
    """
    Retrieve a cached Elentra session from Azure Table Storage.
    Returns (session_cookies_dict, jwt_token) if valid and not expired,
    otherwise returns (None, None).
    """
    try:
        table_client = _get_session_table_client()
        if not table_client:
            return None, None
        
        # Query by RowKey
        entities = list(table_client.query_entities(
            query_filter=f"PartitionKey eq 'session' and RowKey eq '{username}'"
        ))
        
        if not entities:
            print(f"[SESSION DB] No session found for {username}")
            return None, None
        
        entity = entities[0]
        
        # Check expiration
        expires_at_str = entity.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now() > expires_at:
                print(f"[SESSION DB] Session expired for {username} (expired at {expires_at})")
                # Clean up expired session
                try:
                    table_client.delete_entity(partition_key="session", row_key=username)
                except:
                    pass
                return None, None
        
        # Deserialize cookies
        cookies_json = entity.get("session_cookies", "{}")
        try:
            session_cookies = json.loads(cookies_json)
        except:
            session_cookies = {}
        
        jwt_token = entity.get("jwt_token", "")
        
        print(f"[SESSION DB] ✅ Retrieved session for {username} from Azure Table")
        return session_cookies, jwt_token
        
    except Exception as e:
        print(f"[SESSION DB] Get failed for {username}: {e}")
        return None, None

def delete_session(username: str):
    """Delete a session from Azure Table Storage."""
    try:
        table_client = _get_session_table_client()
        if not table_client:
            return False
        
        table_client.delete_entity(partition_key="session", row_key=username)
        print(f"[SESSION DB] ✅ Deleted session for {username}")
        return True
    except Exception as e:
        print(f"[SESSION DB] Delete failed for {username}: {e}")
        return False

def get_storage_status():
    """Get current storage backend status."""
    return {
        "storage_type": STORAGE_TYPE,
        "json_file": DB_FILE,
        "json_exists": os.path.exists(DB_FILE),
        "azure_connected": _table_client is not None,
        "session_table_available": _get_session_table_client() is not None,
        "students_in_cache": len(_cache),
        "encryption_enabled": _cipher is not None
    }