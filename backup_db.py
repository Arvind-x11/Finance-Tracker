import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "finance.db"
BACKUP_DIR = BASE_DIR / "backups"

BACKUP_DIR.mkdir(exist_ok=True)

if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found: {DB_PATH}")

timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_path = BACKUP_DIR / f"finance-{timestamp}.db"

with sqlite3.connect(DB_PATH) as source:
    with sqlite3.connect(backup_path) as destination:
        source.backup(destination)

with sqlite3.connect(backup_path) as check:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]

if result != "ok":
    backup_path.unlink(missing_ok=True)
    raise RuntimeError(f"Backup integrity check failed: {result}")

print(f"Backup successful: {backup_path}")
print("Integrity check: ok")
# Keep only the latest 7 backups
backups = sorted(
    BACKUP_DIR.glob("finance-*.db"),
    key=lambda path: path.stat().st_mtime,
    reverse=True
)

for old_backup in backups[7:]:
    old_backup.unlink()
    print(f"Old backup deleted: {old_backup.name}")