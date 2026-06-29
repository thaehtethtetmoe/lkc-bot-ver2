"""
migrate_to_azure.py
One-time migration: reads existing student_config.json and pushes
all student records into Azure Table Storage.

USAGE:
  Run this ONCE, in the same environment as your deployed app (so it has
  access to the same env vars: AZURE_STORAGE_CONNECTION_STRING,
  STUDENT_CONFIG_KEY, TABLE_NAME).

  Easiest way: open the Azure Portal -> your App Service -> Development
  Tools -> SSH, then in the SSH session:

    cd /home
    python migrate_to_azure.py

  (Upload this file to /home first via Kudu's file browser, or
  Development Tools -> Advanced Tools (Kudu) -> Debug console.)

This script is SAFE to re-run — it uses upsert, so existing rows just
get overwritten with the same data, nothing gets duplicated or lost.
"""

import os
import json

# ── Path to the existing JSON file (the persisted one, not the tmp one) ──
JSON_PATH = "/home/data/student_config.json"


def main():
    if not os.path.exists(JSON_PATH):
        print(f"❌ No file found at {JSON_PATH}. Nothing to migrate.")
        return

    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        print("❌ AZURE_STORAGE_CONNECTION_STRING is not set in this environment.")
        return

    table_name = os.environ.get("TABLE_NAME", "students")

    try:
        from azure.data.tables import TableServiceClient
    except ImportError:
        print("❌ azure-data-tables is not installed in this environment.")
        return

    encryption_key = os.environ.get("STUDENT_CONFIG_KEY")
    cipher = None
    if encryption_key:
        from cryptography.fernet import Fernet
        cipher = Fernet(encryption_key.encode())
    else:
        print("⚠️  STUDENT_CONFIG_KEY not set — passwords in the JSON file "
              "are assumed to already be encrypted with the SAME key your "
              "app normally uses. Without the key here, this script cannot "
              "safely re-encrypt anything, so it will copy the password "
              "field through AS-IS (still encrypted the same way).")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Found {len(data)} student(s) in {JSON_PATH}: {list(data.keys())}")

    service_client = TableServiceClient.from_connection_string(connection_string)
    table_client = service_client.create_table_if_not_exists(table_name)

    migrated = 0
    for username, user_data in data.items():
        # The password in student_config.json is ALREADY encrypted with
        # STUDENT_CONFIG_KEY (your save_json function encrypts before
        # writing to disk). Azure Table also expects it encrypted the
        # same way. So we copy it through unchanged — no decrypt/re-encrypt
        # needed, which avoids ever having a plaintext password in memory
        # during migration.
        entity = {
            "PartitionKey": "student",
            "RowKey": username,
            "username": username,
            "password": user_data.get("password", ""),
            "email": user_data.get("email", ""),
            "registered_at": user_data.get("registered_at", ""),
            "preferences": json.dumps(user_data.get("preferences", {})),
            "bus_config": json.dumps(user_data.get("bus_config", {})),
            "loa_rejection_notified": json.dumps(user_data.get("loa_rejection_notified", [])),
            "updated_at": user_data.get("updated_at", ""),
        }

        try:
            table_client.upsert_entity(entity)
            migrated += 1
            print(f"  ✅ Migrated {username}")
        except Exception as e:
            print(f"  ❌ Failed to migrate {username}: {e}")

    print(f"\nDone. {migrated}/{len(data)} student(s) migrated to Azure Table '{table_name}'.")


if __name__ == "__main__":
    main()