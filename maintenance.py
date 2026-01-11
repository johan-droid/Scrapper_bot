import os
import shutil
import logging
import argparse

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Configuration: Files and Directories to Clean
TARGET_DIRS = ["__pycache__"]
TARGET_EXTENSIONS = [".pyc", ".pyo", ".pyd"]
TARGET_FILES = [
    "output.txt", 
    "inspection.txt", 
    "verification.txt", 
    "format_out.txt", 
    "verified_format.txt",
    "test_cleaning.py" # Optional: Verify if user wants to keep this
]

def clean_system(dry_run=False):
    """
    Recursively cleans cache directories and temporary files.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    logging.info(f"Starting cleanup in: {root_dir}")
    if dry_run:
        logging.info("--- DRY RUN MODE (No files will be deleted) ---")

    cleaned_count = 0
    bytes_freed = 0

    # 1. Walk through directories
    for dirpath, dirnames, filenames in os.walk(root_dir):
        
        # Remove __pycache__ directories
        for d in list(dirnames): # Iterate over a copy to modify safely
            if d in TARGET_DIRS:
                full_path = os.path.join(dirpath, d)
                try:
                    if not dry_run:
                        shutil.rmtree(full_path)
                    logging.info(f"Deleted Directory: {full_path}")
                    cleaned_count += 1
                    dirnames.remove(d) # Prevent walking into deleted dir
                except Exception as e:
                    logging.error(f"Failed to delete directory {full_path}: {e}")

        # Remove specific files and extensions
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            should_delete = False
            
            # Check Extension
            if any(f.endswith(ext) for ext in TARGET_EXTENSIONS):
                should_delete = True
            
            # Check Exact Filename
            if f in TARGET_FILES:
                should_delete = True
            
            if should_delete:
                try:
                    size = os.path.getsize(full_path)
                    if not dry_run:
                        os.remove(full_path)
                    logging.info(f"Deleted File: {full_path}")
                    cleaned_count += 1
                    bytes_freed += size
                except Exception as e:
                    logging.error(f"Failed to delete file {full_path}: {e}")

    logging.info("-" * 30)
    logging.info(f"Cleanup Complete.")
    logging.info(f"Items Removed: {cleaned_count}")
    logging.info(f"Space Freed: {bytes_freed / 1024:.2f} KB")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="System Maintenance & Cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    args = parser.parse_args()
    
    clean_system(dry_run=args.dry_run)
