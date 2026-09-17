"""
Upload generated CSV data into a HubSpot test portal.

Order: companies, then contacts, then deals. Associations and notes are a
separate pass (link_records.py).

The important design decision in here: every record carries a `local_ref`
property holding its ID from the CSV (C0074, P0001, D0203). HubSpot's batch
create endpoint does NOT guarantee that results come back in the same order as
the inputs, so zipping inputs against results silently assigns the wrong
HubSpot ID to the wrong row. That produces data that looks fine until you
notice a contact linked to a stranger's company. Matching on local_ref removes
the assumption entirely.

Run: python upload_data.py
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get("HUBSPOT_TOKEN")
if not TOKEN:
    sys.exit("No HUBSPOT_TOKEN found. Check your .env file.")

BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

DATA = Path("data")
BATCH_SIZE = 100
PAUSE = 0.3

id_map = {"companies": {}, "contacts": {}, "deals": {}}


def load_csv(name):
    with open(DATA / name) as f:
        return list(csv.DictReader(f))


def chunks(rows, size=BATCH_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def save_progress():
    with open("id_map.json", "w") as f:
        json.dump(id_map, f, indent=2)


def days_ago_ms(days):
    return int((time.time() - int(days) * 86400) * 1000)


def ensure_property(object_type, name, label):
    """Create a custom text property if it isn't already there."""
    check = requests.get(f"{BASE}/crm/v3/properties/{object_type}/{name}",
                         headers=HEADERS)
    if check.status_code == 200:
        print(f"  {object_type}.{name} exists")
        return

    group = {"deals": "dealinformation",
             "contacts": "contactinformation",
             "companies": "companyinformation"}[object_type]

    resp = requests.post(f"{BASE}/crm/v3/properties/{object_type}",
                         headers=HEADERS,
                         json={"name": name, "label": label, "type": "string",
                               "fieldType": "text", "groupName": group})
    if resp.status_code == 403:
        sys.exit(f"\nMissing crm.schemas.{object_type}.write scope. Add it to "
                 f"your private app and re-run.\n")
    if resp.status_code not in (200, 201):
        print(f"  FAILED creating {object_type}.{name}: {resp.text[:400]}")
        resp.raise_for_status()
    print(f"  created {object_type}.{name}")
    time.sleep(PAUSE)


def create_batch(object_type, items):
    """Create records and return {local_ref: hubspot_id}.

    items is a list of (local_ref, properties) pairs. Results are matched by
    local_ref, never by position, because HubSpot does not promise order.
    """
    inputs = []
    for ref, props in items:
        inputs.append({"properties": dict(props, local_ref=ref)})

    resp = requests.post(f"{BASE}/crm/v3/objects/{object_type}/batch/create",
                         headers=HEADERS, json={"inputs": inputs})
    time.sleep(PAUSE)

    mapping = {}

    if resp.status_code in (200, 201, 202):
        for r in resp.json()["results"]:
            ref = r["properties"].get("local_ref")
            if ref:
                mapping[ref] = r["id"]
        return mapping

    if resp.status_code != 409:
        print(f"\n  FAILED {resp.status_code} on {object_type}")
        print(f"  {resp.text[:1000]}")
        resp.raise_for_status()

    # Conflict somewhere in the batch: retry one at a time so the other 99
    # still land.
    print("  conflict in batch, retrying individually...")
    for (ref, _props), item in zip(items, inputs):
        one = requests.post(f"{BASE}/crm/v3/objects/{object_type}",
                            headers=HEADERS, json=item)
        time.sleep(0.15)
        if one.status_code in (200, 201):
            mapping[ref] = one.json()["id"]
        elif one.status_code == 409:
            match = re.search(r"Existing ID:\s*(\d+)", one.text)
            if match:
                mapping[ref] = match.group(1)
        else:
            print(f"    skipped {ref}: {one.text[:150]}")
    return mapping


# ---------------------------------------------------------------------------
if Path("id_map.json").exists():
    id_map.update(json.load(open("id_map.json")))
    done = {k: len(v) for k, v in id_map.items() if v}
    if done:
        print(f"Resuming. Already uploaded: {done}")
        print("Delete id_map.json to start over.\n")

print("Ensuring custom properties exist...")
for obj in ("companies", "contacts", "deals"):
    ensure_property(obj, "local_ref", "Local Ref")
ensure_property("contacts", "acquisition_channel", "Acquisition Channel")
ensure_property("deals", "acquisition_channel", "Acquisition Channel")

# --- Companies --------------------------------------------------------------
companies = load_csv("companies.csv")
pending = [r for r in companies if r["company_id"] not in id_map["companies"]]
print(f"\nUploading {len(pending)} companies...")

for batch in chunks(pending):
    items = [(row["company_id"], {
        "name": row["name"],
        "domain": row["domain"],
        "industry": row["industry"],
        "numberofemployees": row["employee_count"],
        "city": row["city"],
    }) for row in batch]
    id_map["companies"].update(create_batch("companies", items))
    save_progress()
    print(f"  {len(id_map['companies'])}/{len(companies)}")

# --- Contacts ---------------------------------------------------------------
# No createdate: HubSpot treats it as read-only on contacts. Staleness comes
# from note timestamps, which are settable.
contacts = load_csv("contacts.csv")
pending = [r for r in contacts if r["contact_id"] not in id_map["contacts"]]
print(f"\nUploading {len(pending)} contacts...")

for batch in chunks(pending):
    items = []
    for row in batch:
        props = {
            "firstname": row["first_name"],
            "lastname": row["last_name"],
            "jobtitle": row["job_title"],
            "acquisition_channel": row["channel"],
        }
        if row["email"]:          # blank email is rejected; omit the key
            props["email"] = row["email"]
        items.append((row["contact_id"], props))

    id_map["contacts"].update(create_batch("contacts", items))
    save_progress()
    print(f"  {len(id_map['contacts'])}/{len(contacts)}")

# --- Deals ------------------------------------------------------------------
deals = load_csv("deals.csv")
pending = [r for r in deals if r["deal_id"] not in id_map["deals"]]
print(f"\nUploading {len(pending)} deals...")

for batch in chunks(pending):
    items = [(row["deal_id"], {
        "dealname": row["name"],
        "amount": row["amount"],
        "dealstage": row["stage"],          # internal ID, not the label
        "pipeline": "default",
        "acquisition_channel": row["channel"],
        "createdate": days_ago_ms(row["created_days_ago"]),
    }) for row in batch]

    id_map["deals"].update(create_batch("deals", items))
    save_progress()
    print(f"  {len(id_map['deals'])}/{len(deals)}")

print(f"""
Records created.
  Companies: {len(id_map['companies'])}
  Contacts:  {len(id_map['contacts'])}
  Deals:     {len(id_map['deals'])}

Next: python link_records.py
""")