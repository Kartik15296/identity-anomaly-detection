"""
Populate Database: Full DB Population Pipeline
This script handles all database operations:
1. Clears the entire database
2. Reads data from preprocessed CSV
3. Processes events, profiles, and clusters in a single pass
4. Batch inserts to database

Optimization: No redundant DB reads - calculate everything in memory
then make insert/update calls only.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from database_crud import db


def clear_database():
    """Clears all collections from the database."""
    print("[POPULATE] Clearing database...")
    try:
        db.login_events.delete_many({})
        db.feedback_labels.delete_many({})
        db.user_profiles.delete_many({})
        db.peer_clusters.delete_many({})
        db.registries.delete_many({})
        print("[POPULATE] ✓ Database cleared successfully")
    except Exception as e:
        print(f"[POPULATE] ✗ Error clearing database: {e}")
        raise


def load_csv_data(csv_path="database/rba-preprocessed-database.csv"):
    """Loads raw data from CSV file."""
    print(f"[POPULATE] Loading data from CSV: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
        print(f"[POPULATE] ✓ Loaded {len(df)} records from CSV")
        return df
    except Exception as e:
        print(f"[POPULATE] ✗ Error loading CSV: {e}")
        raise


def process_all_data(df, batch_size=100):
    """
    Single-pass data processing:
    - Processes events, builds profiles, and clusters all at once
    - Returns: (events_list, profiles_list, clusters_list)
    
    NO DB READS - everything calculated in memory in one pass
    """
    print(f"[POPULATE] Processing {len(df)} rows in single pass...")
    
    events = []
    user_profiles = defaultdict(lambda: {
        "event_count": 0,
        "ips": set(),
        "countries": set(),
        "browsers": set(),
        "devices": set(),
        "first_seen": None,
        "last_seen": None,
    })
    
    # Single pass through all rows
    for idx, row in df.iterrows():
        try:
            # Create event
            event = {
                "event_id": str(idx),
                "user_id": str(row["User ID"]),
                "timestamp": str(row["Login Timestamp"]),
                "ip_address": str(row["IP Address"]),
                "country": str(row["Country"]),
                "region": str(row["Region"]),
                "city": str(row["City"]),
                "asn": str(row["ASN"]),
                "user_agent": str(row["User Agent String"]),
                "browser_name": str(row["Browser Name and Version"]),
                "os_name": str(row["OS Name and Version"]),
                "device_type": str(row["Device Type"]),
                "login_success": bool(row["Login Successful"]),
                "is_attack": bool(row["Is Attack IP"]),
                "is_account_takeover": bool(row["Is Account Takeover"]),
                "department": str(row["department"]),
                "role": str(row["role"]),
                "office": str(row["office"]),
                "mfa_triggered": str(row["mfa_triggered"]),
            }
            
            events.append(event)
            
            # Build profile data in-memory
            user_id = event["user_id"]
            profile = user_profiles[user_id]
            
            profile["event_count"] += 1
            if event["ip_address"]:
                profile["ips"].add(event["ip_address"])
            if event["country"]:
                profile["countries"].add(event["country"])
            if event["browser_name"]:
                profile["browsers"].add(event["browser_name"])
            if event["device_type"]:
                profile["devices"].add(event["device_type"])
            
            # Track first and last seen
            if profile["first_seen"] is None:
                profile["first_seen"] = event["timestamp"]
            profile["last_seen"] = event["timestamp"]
            
            # Store org info (same for all user's events)
            profile["department"] = event["department"]
            profile["role"] = event["role"]
            profile["office"] = event["office"]
            
        except Exception as e:
            print(f"[POPULATE] ⚠ Skipping event {idx}: {e}")
            continue
    
    print(f"[POPULATE] ✓ Processed {len(events)} events for {len(user_profiles)} users")
    
    # Convert profiles from sets to lists and format for DB
    profiles_list = []
    for user_id, profile in user_profiles.items():
        profiles_list.append({
            "user_id": user_id,
            "department": profile["department"],
            "role": profile["role"],
            "office": profile["office"],
            "event_count": profile["event_count"],
            "first_seen": profile["first_seen"],
            "last_seen": profile["last_seen"],
            "trusted_ips": list(profile["ips"]),
            "trusted_countries": list(profile["countries"]),
            "trusted_browsers": list(profile["browsers"]),
            "trusted_devices": list(profile["devices"]),
            "created_at": datetime.now().isoformat(),
        })
    
    # Build clusters from profiles (in-memory)
    clusters_map = defaultdict(lambda: {
        "member_ids": [],
        "size": 0,
    })
    
    for profile in profiles_list:
        user_id = profile["user_id"]
        dept = profile["department"]
        role = profile["role"]
        cluster_key = f"cluster_{dept}_{role}".lower().replace(" ", "_")
        
        clusters_map[cluster_key]["member_ids"].append(user_id)
        clusters_map[cluster_key]["size"] += 1
        clusters_map[cluster_key]["department"] = dept
        clusters_map[cluster_key]["role"] = role
    
    # Format clusters for DB
    clusters_list = []
    for cluster_id, cluster in clusters_map.items():
        clusters_list.append({
            "cluster_id": cluster_id,
            "department": cluster["department"],
            "role": cluster["role"],
            "member_ids": cluster["member_ids"],
            "size": cluster["size"],
            "created_at": datetime.now().isoformat(),
        })
    
    print(f"[POPULATE] ✓ Built {len(clusters_list)} clusters")
    
    return events, profiles_list, clusters_list


def batch_insert_events(events, batch_size=100):
    """Insert events in batches to DB."""
    print(f"\n[POPULATE] Inserting {len(events)} events in batches...")
    
    for i in range(0, len(events), batch_size):
        batch = events[i:i+batch_size]
        try:
            db.login_events.insert_many(batch)
            progress = (i // batch_size) + 1
            total_batches = (len(events) - 1) // batch_size + 1
            print(f"[POPULATE] ✓ Inserted batch {progress}/{total_batches}")
        except Exception as e:
            print(f"[POPULATE] ✗ Error inserting batch: {e}")
            return False
    
    return True


def batch_insert_profiles(profiles, batch_size=50):
    """Insert profiles in batches to DB."""
    print(f"\n[POPULATE] Inserting {len(profiles)} user profiles in batches...")
    
    for i in range(0, len(profiles), batch_size):
        batch = profiles[i:i+batch_size]
        try:
            db.user_profiles.insert_many(batch)
            progress = (i // batch_size) + 1
            total_batches = (len(profiles) - 1) // batch_size + 1
            print(f"[POPULATE] ✓ Inserted batch {progress}/{total_batches}")
        except Exception as e:
            print(f"[POPULATE] ✗ Error inserting batch: {e}")
            return False
    
    return True


def batch_insert_clusters(clusters):
    """Insert clusters to DB."""
    print(f"\n[POPULATE] Inserting {len(clusters)} clusters...")
    
    try:
        db.peer_clusters.insert_many(clusters)
        print(f"[POPULATE] ✓ Inserted all {len(clusters)} clusters")
        return True
    except Exception as e:
        print(f"[POPULATE] ✗ Error inserting clusters: {e}")
        return False


def main(csv_path="database/rba-preprocessed-database.csv"):
    """Main database population pipeline - optimized single pass."""
    print("\n" + "=" * 70)
    print("POPULATE DB: Full Database Population Pipeline (Optimized)")
    print("=" * 70 + "\n")
    
    try:
        # Step 1: Clear database
        clear_database()
        
        # Step 2: Load CSV
        df = load_csv_data(csv_path)
        
        # Step 3: Process all data in single pass (events + profiles + clusters)
        events, profiles, clusters = process_all_data(df)
        
        # Step 4: Batch insert to DB (only write operations)
        events_ok = batch_insert_events(events)
        profiles_ok = batch_insert_profiles(profiles) if events_ok else False
        clusters_ok = batch_insert_clusters(clusters) if profiles_ok else False
        
        # Final summary
        print("\n" + "=" * 70)
        if events_ok and profiles_ok and clusters_ok:
            print("✓ DATABASE POPULATION COMPLETE")
            print(f"  - Events: {len(events)}")
            print(f"  - User Profiles: {len(profiles)}")
            print(f"  - Peer Clusters: {len(clusters)}")
        else:
            print("⚠ DATABASE POPULATION PARTIAL - Some inserts failed")
        print("=" * 70 + "\n")
    
    except Exception as e:
        print(f"\n✗ DATABASE POPULATION FAILED: {e}\n")
        raise


if __name__ == "__main__":
    import sys
    
    csv_path = "database/rba-preprocessed-database.csv"
    
    # Allow CSV path override
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    
    main(csv_path)
