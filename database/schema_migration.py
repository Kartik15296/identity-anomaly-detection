import pymongo
from pymongo import MongoClient, ASCENDING
import mock_db  

# --- CONFIGURATION ---
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import os

load_dotenv()

user = os.getenv("MONGODB_USER")
password = os.getenv("MONGODB_PASSWORD")
cluster = os.getenv("MONGODB_CLUSTER")

uri = f"mongodb+srv://{user}:{password}@{cluster}/?appName=Cluster0"
DB_NAME = "Iddentity_Anamoly_detection"

def run_migration():
    client = MongoClient(uri, server_api=ServerApi('1'))
    db = client[DB_NAME]

    print("🚀 Starting Migration to MongoDB...")

    # 1. Setup Collections
    collections = ["login_events", "user_profiles", "peer_clusters", "feedback_labels", "registries"]
    
    # Optional: Clear existing data for a clean start
    for col in collections:
        db[col].delete_many({})

    # 2. Insert Data from mock_db
    # Login events is already a list of dicts
    db.login_events.insert_many(mock_db.LOGIN_EVENTS)

    # Convert dict-of-dicts to lists for MongoDB insertion
    db.user_profiles.insert_many(list(mock_db.USER_PROFILES.values()))
    db.peer_clusters.insert_many(list(mock_db.PEER_CLUSTERS.values()))
    db.feedback_labels.insert_many(mock_db.FEEDBACK_LABELS)

    # Store Registries as a single config document
    db.registries.insert_one({
        "type": "org_mappings",
        "departments": mock_db.DEPARTMENT_REGISTRY,
        "roles": mock_db.ROLE_REGISTRY,
        "offices": mock_db.OFFICE_REGISTRY
    })

    # 3. Create Performance Indexes (Crucial for Anomaly Detection)
    print("Indexing collections for performance...")
    db.login_events.create_index([("user_id", ASCENDING)])
    db.login_events.create_index([("event_id", ASCENDING)], unique=True)
    db.user_profiles.create_index([("user_id", ASCENDING)], unique=True)
    
    print("✅ Migration Successful: Data is now live in Atlas.")

if __name__ == "__main__":
    run_migration()