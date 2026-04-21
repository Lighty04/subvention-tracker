"""CLI for running subvention imports - runnable via cron."""
import asyncio
import sys
import os
import argparse

from .models import SessionLocal, init_db
from .scraper import import_recent_subventions
from .seeds import seed_watched_associations

def main():
    parser = argparse.ArgumentParser(description="Import subventions from Paris Open Data")
    parser.add_argument("--max-records", type=int, default=500, help="Max records to import")
    parser.add_argument("--seed", action="store_true", help="Seed watched associations first")
    args = parser.parse_args()
    
    init_db()
    
    db = SessionLocal()
    try:
        if args.seed:
            count = seed_watched_associations(db)
            print(f"Seeded {count} watched associations")
        
        print(f"Starting import (max {args.max_records} records)...")
        log = asyncio.run(import_recent_subventions(db, args.max_records))
        print(f"Import {log.status}: {log.records_imported} imported, {log.records_updated} updated")
        if log.error_message:
            print(f"Error: {log.error_message}")
            sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
