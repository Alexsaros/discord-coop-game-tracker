import datetime
import os
import shutil

from database.db import DATABASE_FILE
from shared.logger import log

BACKUP_DIRECTORY = "backups"
MAX_BACKUPS = 20


def create_backup(file_to_backup=DATABASE_FILE):
    # Ensure the backup directory exists
    os.makedirs(BACKUP_DIRECTORY, exist_ok=True)

    # Create a new backup with a timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(file_to_backup)
    backup_filepath = os.path.join(BACKUP_DIRECTORY, f"{filename}_{timestamp}.bak")
    shutil.copy2(file_to_backup, backup_filepath)
    log(f"Created backup: {backup_filepath}")

    # Get all the backups for the requested file, and sort them from old to new
    relevant_backups = [os.path.join(BACKUP_DIRECTORY, f) for f in os.listdir(BACKUP_DIRECTORY) if f.startswith(filename) and f.endswith(".bak")]
    backups = sorted(relevant_backups, key=os.path.getctime)

    # Remove the oldest backups if we have too many
    while len(backups) > MAX_BACKUPS:
        oldest_backup = backups.pop(0)
        os.remove(oldest_backup)
        log(f"Deleted old backup: {oldest_backup}")
