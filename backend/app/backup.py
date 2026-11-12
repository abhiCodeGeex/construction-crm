"""Phase I block 7 — daily backups (§15 "daily backups", §18 "backups status and restore").

Every day at BACKUP_HOUR (local server time) the `backup` service writes /data/backups/<YYYYmmdd-HHMM>/ with
one gzipped JSON file per collection (Mongo extended JSON, so ids and dates come back exactly) and a tar.gz of the
uploaded files, keeps the last BACKUP_KEEP days, and records the result in `platform_settings._id = "backup"`, which
the Super Admin dashboard shows.

    python -m app.backup              # run forever (the docker service)
    python -m app.backup now          # one backup now
    python -m app.backup restore <folder> [--yes]   # replace the database (and uploads) from a backup folder
"""
import gzip
import os
import shutil
import sys
import tarfile
import time
from datetime import datetime

from bson import json_util

from .config import Config
from .db import db

BACKUP_DIR = os.getenv("BACKUP_DIR", "/data/backups")
KEEP = int(os.getenv("BACKUP_KEEP", "14"))
HOUR = int(os.getenv("BACKUP_HOUR", "2"))


def folder_size(path):
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, files in os.walk(path) for f in files)


def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        p = os.path.join(BACKUP_DIR, name)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "DONE")):
            out.append({"name": name, "size": folder_size(p), "collections": len([f for f in os.listdir(p) if f.endswith(".json.gz")])})
    return out


def run_backup(reason="daily"):
    started = datetime.utcnow()
    name = started.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, name)
    os.makedirs(path, exist_ok=True)
    try:
        counts = {}
        for coll in db.list_collection_names():
            with gzip.open(os.path.join(path, f"{coll}.json.gz"), "wt", encoding="utf8") as f:
                n = 0
                for doc in db[coll].find():
                    f.write(json_util.dumps(doc) + "\n")
                    n += 1
            counts[coll] = n
        if os.path.isdir(Config.UPLOAD_DIR):
            with tarfile.open(os.path.join(path, "uploads.tar.gz"), "w:gz") as tar:
                tar.add(Config.UPLOAD_DIR, arcname="uploads")
        open(os.path.join(path, "DONE"), "w").write(started.isoformat())
        for old in list_backups()[KEEP:]:
            shutil.rmtree(os.path.join(BACKUP_DIR, old["name"]), ignore_errors=True)
        status = {"status": "ok", "last_ok": started, "last_name": name, "size": folder_size(path), "documents": sum(counts.values()),
                  "reason": reason, "error": None}
    except Exception as e:  # keep the error for the dashboard; a half-written folder is removed
        shutil.rmtree(path, ignore_errors=True)
        status = {"status": "failed", "error": str(e)[:300], "failed_at": started, "reason": reason}
    db.platform_settings.update_one({"_id": "backup"}, {"$set": {**status, "ran_at": datetime.utcnow()}}, upsert=True)
    return status


def restore(name, uploads=True):
    """Replace every collection with the backup's copy (and the uploads folder)."""
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(os.path.join(path, "DONE")):
        raise SystemExit(f"{name} is not a complete backup")
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".json.gz"):
            continue
        coll = fn[:-8]
        docs = []
        with gzip.open(os.path.join(path, fn), "rt", encoding="utf8") as f:
            for line in f:
                if line.strip():
                    docs.append(json_util.loads(line))
        db[coll].delete_many({})
        if docs:
            db[coll].insert_many(docs)
    tar = os.path.join(path, "uploads.tar.gz")
    if uploads and os.path.exists(tar):
        shutil.rmtree(Config.UPLOAD_DIR, ignore_errors=True)
        with tarfile.open(tar) as t:
            t.extractall(os.path.dirname(Config.UPLOAD_DIR.rstrip("/")), filter="data")
        src = os.path.join(os.path.dirname(Config.UPLOAD_DIR.rstrip("/")), "uploads")
        if os.path.abspath(src) != os.path.abspath(Config.UPLOAD_DIR):
            shutil.move(src, Config.UPLOAD_DIR)
    db.platform_settings.update_one({"_id": "backup"}, {"$set": {"restored_from": name, "restored_at": datetime.utcnow()}}, upsert=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "now":
        print(run_backup("manual"))
        return
    if len(sys.argv) > 2 and sys.argv[1] == "restore":
        if "--yes" not in sys.argv:
            raise SystemExit("This replaces the whole database. Run again with --yes to go ahead.")
        restore(sys.argv[2])
        print("restored", sys.argv[2])
        return
    while True:  # the service: once a day at HOUR
        now = datetime.now()
        last = (db.platform_settings.find_one({"_id": "backup"}) or {}).get("last_ok")
        if now.hour >= HOUR and (not last or last.date() < datetime.utcnow().date()):
            run_backup()
        time.sleep(300)


if __name__ == "__main__":
    main()
