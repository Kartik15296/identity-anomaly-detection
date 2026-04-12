"""
Create CSV: Base Dataset Generation
Single responsibility: Create rba-preprocessed-database.csv from raw data
- Reads raw_identity_data.csv in chunks
- Filters out null rows
- Accumulates first 2 lakhs (200,000) non-null rows
- Saves to rba-preprocessed-database.csv
"""

import pandas as pd
import os


def create_base_dataset(input_file, output_file, chunk_size=10000, max_rows=200000):
    """
    Creates base preprocessed CSV from raw data using chunk processing.
    - Reads in chunks to handle large files
    - Removes rows with null values
    - Accumulates first max_rows non-null rows
    - Saves to output file
    """
    print("=" * 70)
    print("CREATE CSV: Base Dataset Generation")
    print("=" * 70 + "\n")
    
    print(f"[CREATE] Reading raw data from {input_file} (chunk_size={chunk_size})...")
    
    try:
        total_processed = 0
        total_written = 0
        first_chunk = True
        
        # Remove output file if it exists
        if os.path.exists(output_file):
            print(f"[CREATE] Removing existing {output_file}...")
            os.remove(output_file)
        
        # Process in chunks
        for chunk in pd.read_csv(input_file, chunksize=chunk_size):
            total_processed += len(chunk)
            
            # Drop rows with null values
            chunk = chunk.dropna()
            
            # Only write if there are rows after filtering
            if len(chunk) > 0:
                mode = 'w' if first_chunk else 'a'
                header = first_chunk
                
                chunk.to_csv(output_file, mode=mode, header=header, index=False)
                
                first_chunk = False
                total_written += len(chunk)
                
                print(f"[CREATE] Processed {total_processed} rows → Written {total_written}/{max_rows} non-null rows")
                
                # Stop if we have enough non-null rows
                if total_written >= max_rows:
                    print(f"\n[CREATE] ✓ Reached target of {max_rows} non-null rows. Stopping.")
                    break
        
        print(f"\n[CREATE] ✓ Successfully created {output_file}")
        print(f"[CREATE] ✓ Total input rows processed: {total_processed}")
        print(f"[CREATE] ✓ Final dataset: {total_written} rows (all non-null)")
        print("=" * 70 + "\n")
        
        return True
    
    except FileNotFoundError:
        print(f"[CREATE] ✗ Error: {input_file} not found")
        return False
    except Exception as e:
        print(f"[CREATE] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    INPUT_CSV = os.path.join(script_dir, "raw_identity_data.csv")
    OUTPUT_CSV = os.path.join(script_dir, "rba-preprocessed-database.csv")
    CHUNK_SIZE = 5000
    MAX_ROWS = 200000  # 2 Lakhs
    
    create_base_dataset(
        input_file=INPUT_CSV,
        output_file=OUTPUT_CSV,
        chunk_size=CHUNK_SIZE,
        max_rows=MAX_ROWS
    )
