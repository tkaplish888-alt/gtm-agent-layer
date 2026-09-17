"""
Create associations and upload notes. Run after upload_data.py.

Associations use HubSpot's v4 "default" endpoint, which lets the API choose
the correct association type itself. Passing a type ID you guessed at fails
silently: the record is created, the link is not, and nothing tells you. This
endpoint either works or returns an error.

Run: python link_records.py
"""

import csv
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
HEADERS = {"Authorization": f"Bearer {os.environ['HUBSPOT_TOKEN']}",
           "Content-Type": "application/json"}
BASE = "https://api.hubapi.com"
DATA = Path("data")

id_map = json.load(open("id_map.json"))
done = set(json.load(open("link_progress.json"))) if Path("link_progress.json").exists() else set()


def load_csv(name):
    with open(DATA / name) as f:
        return list(csv.DictReader(f))


def save_done():
    with open("link_progress.json", "w") as f:
        json.dump(sorted(done), f)


def link(from_type, from_id, to_type, to_id, key):
    """Default association. Returns True on success."""
    if key in done:
        return True
    url = (f"{BASE}/crm/v4/objects/{from_type}/{from_id}"
           f"/associations/default/{to_type}/{to_id}")
    resp = requests.put(url, headers=HEADERS)
    time.sleep(0.1)
    if resp.status_code in (200, 201, 204):
        done.add(key)
        return True
    print(f"  {resp.status_code} on {key}: {resp.text[:160]}")
    return False


def days_ago_ms(days):
    return int((time.time() - int(days) * 86400) * 1000)


# --- Contact -> Company -----------------------------------------------------
contacts = load_csv("contacts.csv")
print(f"Linking contacts to companies...")
n = 0
for row in contacts:
    cid = id_map["contacts"].get(row["contact_id"])
    comp = id_map["companies"].get(row["company_id"])
    if cid and comp and link("contacts", cid, "companies", comp,
                             f"c2co:{row['contact_id']}"):
        n += 1
        if n % 100 == 0:
            print(f"  {n}")
            save_done()
save_done()
print(f"  {n} linked")

# --- Deal -> Contact and Deal -> Company ------------------------------------
deals = load_csv("deals.csv")
print(f"\nLinking deals...")
n = 0
for row in deals:
    did = id_map["deals"].get(row["deal_id"])
    cid = id_map["contacts"].get(row["contact_id"])
    comp = id_map["companies"].get(row["company_id"])
    if not did:
        continue
    if cid:
        link("deals", did, "contacts", cid, f"d2c:{row['deal_id']}")
    if comp:
        link("deals", did, "companies", comp, f"d2co:{row['deal_id']}")
    n += 1
    if n % 100 == 0:
        print(f"  {n}")
        save_done()
save_done()
print(f"  {n} deals linked")

# --- Notes ------------------------------------------------------------------
# The engagement trail. Without backdated notes there is no way to answer
# "who has gone quiet", which is the whole point of the project.
engagements = load_csv("engagements.csv")
pending = [e for e in engagements if f"note:{e['engagement_id']}" not in done]
print(f"\nUploading {len(pending)} notes...")

for i in range(0, len(pending), 100):
    batch = pending[i:i + 100]
    inputs = []
    keys = []
    for row in batch:
        cid = id_map["contacts"].get(row["contact_id"])
        if not cid:
            continue
        inputs.append({
            "properties": {
                "hs_note_body": f"[{row['type']}] {row['summary']}",
                "hs_timestamp": days_ago_ms(row["days_ago"]),
            },
            "associations": [{
                "to": {"id": cid},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 202}],   # note -> contact
            }],
        })
        keys.append(f"note:{row['engagement_id']}")

    if not inputs:
        continue

    resp = requests.post(f"{BASE}/crm/v3/objects/notes/batch/create",
                         headers=HEADERS, json={"inputs": inputs})
    time.sleep(0.3)
    if resp.status_code in (200, 201, 202):
        done.update(keys)
        save_done()
        print(f"  {len([k for k in done if k.startswith('note:')])}/{len(engagements)}")
    else:
        print(f"  FAILED {resp.status_code}: {resp.text[:600]}")
        break

print("\nDone. Next: python fix_ground_truth.py")