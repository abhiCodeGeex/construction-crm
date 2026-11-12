"""Remove what a test run with KEEP=1 left in the demo company: projects whose name starts with the given prefix,
their money, documents and leads.   docker compose exec backend python tests/cleanup_kept.py "PhaseI"
"""
import os
import sys

from bson import ObjectId
from pymongo import MongoClient

mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"))[os.getenv("MONGO_DB", "buildsuite")]
prefix = sys.argv[1] if len(sys.argv) > 1 else "PhaseI"
projects = list(mongo.projects.find({"name": {"$regex": f"^{prefix}"}}, {"lead_id": 1, "company_id": 1, "client_id": 1}))
pids = [str(p["_id"]) for p in projects]
lids = [p["lead_id"] for p in projects if p.get("lead_id")]
for col in mongo.list_collection_names():
    if col in ("projects", "leads"):
        continue
    n = mongo[col].delete_many({"project_id": {"$in": pids}}).deleted_count if pids else 0
    n += mongo[col].delete_many({"lead_id": {"$in": lids}}).deleted_count if lids else 0
    if n:
        print(col, n)
mongo.petty_cash.delete_many({"company_id": {"$in": list({p["company_id"] for p in projects})}})
mongo.projects.delete_many({"_id": {"$in": [ObjectId(x) for x in pids]}})
mongo.leads.delete_many({"_id": {"$in": [ObjectId(x) for x in lids]}})
mongo.contacts.delete_many({"name": {"$regex": "^Ira Client"}})
print("removed", len(pids), "project(s),", len(lids), "lead(s)")
