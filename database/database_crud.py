# --- DATABASE CONNECTION ---
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import os

load_dotenv()

user = os.getenv("MONGODB_USER")
password = os.getenv("MONGODB_PASSWORD")
cluster = os.getenv("MONGODB_CLUSTER")

uri = f"mongodb+srv://{user}:{password}@{cluster}/?appName=Cluster0"
client = MongoClient(uri, server_api=ServerApi('1'))

db = client["Iddentity_Anamoly_detection"]

# --- READ OPERATIONS ---

def get_user_profile(user_id):
    """Fetches a specific user profile. Removes Mongo _id for ML compatibility."""
    return db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})

def get_user_events(user_id, limit=50):
    """Returns a list of the most recent login events for a user."""
    return list(db.login_events.find({"user_id": user_id}, {"_id": 0}).sort("timestamp", -1).limit(limit))

def get_peer_cluster(cluster_id):
    return db.peer_clusters.find_one({"cluster_id": cluster_id}, {"_id": 0})

# --- CREATE / UPDATE OPERATIONS ---

def log_new_event(event_data):
    """Logs a new login attempt into the DB."""
    return db.login_events.insert_one(event_data)

def update_feedback(event_id, label, source, notes=""):
    """Updates or inserts a security feedback label for an event."""
    query = {"event_id": event_id}
    new_data = {
        "$set": {
            "label": label,
            "source": source,
            "notes": notes
        }
    }
    return db.feedback_labels.update_one(query, new_data, upsert=True)

# --- DELETE OPERATIONS ---

def remove_events(event_id):
    """Deletes an event and its associated feedback (for testing purposes)."""
    db.login_events.delete_one({"event_id": event_id})
    db.feedback_labels.delete_one({"event_id": event_id})

# --- REGISTRY HELPERS (For K-Means Encodings) ---

def get_category_index(category, value):
    """
    category: 'departments', 'roles', or 'offices'
    value: e.g., 'Engineering'
    """
    doc = db.registries.find_one({"type": "org_mappings"})
    mapping = doc.get(category, {})
    
    if value in mapping:
        return mapping[value]
    
    # If new category appears (e.g., a new branch office), add it
    new_idx = max(mapping.values() or [-1]) + 1
    db.registries.update_one(
        {"type": "org_mappings"},
        {"$set": {f"{category}.{value}": new_idx}}
    )
    return new_idx


# --- BATCH OPERATIONS (For Training & Monitoring) ---

def get_all_login_events():
    """Fetches all login events from the database. Used for training and drift monitoring."""
    return list(db.login_events.find({}, {"_id": 0}))

def get_all_feedback_labels():
    """Fetches all feedback labels from the database. Used for supervised training."""
    return list(db.feedback_labels.find({}, {"_id": 0}))

def get_all_user_profiles():
    """Fetches all user profiles from the database. Used for profiling and clustering."""
    return list(db.user_profiles.find({}, {"_id": 0}))

def get_all_peer_clusters():
    """Fetches all peer clusters from the database."""
    return list(db.peer_clusters.find({}, {"_id": 0}))

def get_event_by_id(event_id):
    """Fetches a specific event by event_id. Convenience function for compatibility."""
    return db.login_events.find_one({"event_id": event_id}, {"_id": 0})


# --- MAIN TEST FUNCTION ---

def main():
    """Test all CRUD operations."""
    print("=" * 60)
    print("TESTING DATABASE CRUD OPERATIONS")
    print("=" * 60)
    
    # Test 1: get_user_profile
    print("\n[1] Testing get_user_profile()...")
    try:
        user_id = "u01"
        profile = get_user_profile(user_id)
        print(f"    ✓ User profile for {user_id}: {profile}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 2: get_user_events
    print("\n[2] Testing get_user_events()...")
    try:
        user_id = "u01"
        events = get_user_events(user_id, limit=5)
        print(f"    ✓ Retrieved {len(events)} events for {user_id}")
        if events:
            print(f"    Sample event: {events[0]}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 3: get_peer_cluster
    print("\n[3] Testing get_peer_cluster()...")
    try:
        cluster_id = "cluster_eng_blr"
        cluster = get_peer_cluster(cluster_id)
        print(f"    ✓ Peer cluster {cluster_id}: {cluster}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 4: log_new_event
    print("\n[4] Testing log_new_event()...")
    try:
        test_event = {
            "event_id": "test_event_001",
            "user_id": "test_user",
            "timestamp": "2026-04-05T10:00:00Z",
            "action": "login"
        }
        result = log_new_event(test_event)
        print(f"    ✓ Event logged: {result.inserted_id}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 5: update_feedback
    print("\n[5] Testing update_feedback()...")
    try:
        event_id = "test_event_001"
        result = update_feedback(event_id, label="benign", source="manual", notes="Test feedback")
        print(f"    ✓ Feedback updated for event {event_id}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 6: get_category_index
    print("\n[6] Testing get_category_index()...")
    try:
        idx1 = get_category_index("departments", "Engineering")
        print(f"    ✓ Department 'Engineering' index: {idx1}")
        idx2 = get_category_index("roles", "Admin")
        print(f"    ✓ Role 'Admin' index: {idx2}")
        idx3 = get_category_index("offices", "New York")
        print(f"    ✓ Office 'New York' index: {idx3}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    # Test 7: remove_events
    print("\n[7] Testing remove_events()...")
    try:
        event_id = "test_event_001"
        remove_events(event_id)
        print(f"    ✓ Event {event_id} and associated feedback removed")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()