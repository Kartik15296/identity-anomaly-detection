"""
Preprocess CSV: Data Enrichment and Normalization
Takes rba-preprocessed-database.csv and:
1. Removes Round-Trip Time [ms] column
2. Remaps User IDs to sequential (0, 1, 2, ...)
3. Assigns department/role/office to each unique user (consistently)
4. Saves updated file back
"""

import pandas as pd
import numpy as np
import os


# --- MOCK DATA CONSTANTS ---
DEPARTMENTS = [
    "Engineering", "Sales", "Marketing", "Finance", 
    "HR", "Legal", "IT Support", "Operations", "Executive"
]

ROLES = [
    "Intern", "Contractor", "Staff", "Senior Staff", 
    "Manager", "Senior Manager", "Director", "VP", 
    "C-Level", "Service Account"
]

OFFICES = [
    "Bangalore", "London", "New York", "Singapore", 
    "Remote", "Tokyo", "Berlin"
]


def preprocess_csv(input_file, output_file):
    """
    Preprocesses the CSV file:
    1. Remove Round-Trip Time [ms]
    2. Remap User IDs to sequential
    3. Assign department/role/office per unique user (consistently)
    4. Save updated file
    """
    print("=" * 70)
    print("PREPROCESS CSV: Data Enrichment and Normalization")
    print("=" * 70 + "\n")
    
    try:
        print(f"[PREPROCESS] Reading {input_file}...")
        df = pd.read_csv(input_file)
        print(f"[PREPROCESS] ✓ Loaded {len(df)} rows")
        
        # Step 1: Remove Round-Trip Time [ms] column if it exists
        print(f"\n[PREPROCESS] Step 1: Removing unnecessary columns...")
        if 'Round-Trip Time [ms]' in df.columns:
            df = df.drop(columns=['Round-Trip Time [ms]','index'])
            print(f"[PREPROCESS] ✓ Removed 'Round-Trip Time [ms]'")
        
        # Step 2: Remap User IDs to sequential
        print(f"\n[PREPROCESS] Step 2: Remapping User IDs...")
        unique_user_ids = df['User ID'].unique()
        user_id_mapping = {old_id: new_id for new_id, old_id in enumerate(unique_user_ids)}
        
        print(f"[PREPROCESS] ✓ Found {len(unique_user_ids)} unique users")
        print(f"[PREPROCESS] ✓ Sample mapping: {list(user_id_mapping.items())[:5]}")
        
        # Apply mapping
        df['User ID'] = df['User ID'].map(user_id_mapping)
        
        # Step 3: Assign department/role/office per unique user (consistently)
        print(f"\n[PREPROCESS] Step 3: Assigning user attributes...")
        
        # Create consistent assignments for each user
        user_attributes = {}
        for user_id in range(len(unique_user_ids)):
            np.random.seed(user_id)  # Seed by user_id for consistency
            user_attributes[user_id] = {
                "department": np.random.choice(DEPARTMENTS),
                "role": np.random.choice(ROLES),
                "office": np.random.choice(OFFICES),
            }
        
        # Apply attributes to all rows
        df['department'] = df['User ID'].map(lambda uid: user_attributes[uid]["department"])
        df['role'] = df['User ID'].map(lambda uid: user_attributes[uid]["role"])
        df['office'] = df['User ID'].map(lambda uid: user_attributes[uid]["office"])
        
        print(f"[PREPROCESS] ✓ Assigned department/role/office to {len(user_attributes)} users")
        
        # Add mfa_triggered column
        np.random.seed(42)  # Global seed for reproducibility
        df['mfa_triggered'] = np.random.choice(['yes', 'no'], size=len(df))
        
        # Step 4: Save updated file
        print(f"\n[PREPROCESS] Step 4: Saving preprocessed file...")
        df.to_csv(output_file, index=False)
        
        print(f"\n[PREPROCESS] ✓ Successfully saved to {output_file}")
        print(f"[PREPROCESS] ✓ Final dataset: {len(df)} rows, {len(df.columns)} columns")
        
        # Print summary
        print(f"\n[PREPROCESS] Summary:")
        print(f"  - Total rows: {len(df)}")
        print(f"  - Unique users: {len(unique_user_ids)}")
        print(f"  - Columns: {', '.join(df.columns)}")
        print(f"  - Sample user attributes:")
        for uid in range(min(5, len(user_attributes))):
            attrs = user_attributes[uid]
            print(f"    User {uid}: {attrs['department']} / {attrs['role']} / {attrs['office']}")
        
        print("=" * 70 + "\n")
        
        return True
    
    except FileNotFoundError:
        print(f"[PREPROCESS] ✗ Error: {input_file} not found")
        return False
    except Exception as e:
        print(f"[PREPROCESS] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    INPUT_CSV = os.path.join(script_dir, "rba-preprocessed-database.csv")
    OUTPUT_CSV = os.path.join(script_dir, "rba-preprocessed-database.csv")
    
    preprocess_csv(
        input_file=INPUT_CSV,
        output_file=OUTPUT_CSV
    )
