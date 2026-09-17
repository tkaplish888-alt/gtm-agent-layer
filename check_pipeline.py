"""
Print the real pipeline and deal stage IDs from your HubSpot portal.

Run this BEFORE generating or uploading anything. Stage IDs are portal- and
pipeline-specific. HubSpot's default sales pipeline uses readable keys like
"appointmentscheduled", but any pipeline created after the fact uses generated
numeric IDs instead. Guessing costs an hour; asking costs four seconds.

Run: python check_pipeline.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["HUBSPOT_TOKEN"]

resp = requests.get(
    "https://api.hubapi.com/crm/v3/pipelines/deals",
    headers={"Authorization": f"Bearer {TOKEN}"},
)

if resp.status_code != 200:
    print(f"Failed: {resp.status_code}")
    print(resp.text)  # the error body tells you exactly what's wrong
    raise SystemExit(1)

for pipeline in resp.json()["results"]:
    print(f"\nPIPELINE: {pipeline['label']}")
    print(f"  id: {pipeline['id']}")
    print(f"  {'stage id':<28} {'label':<30} closed?")
    print(f"  {'-' * 28} {'-' * 30} -------")

    stages = sorted(pipeline["stages"], key=lambda s: s["displayOrder"])
    for stage in stages:
        closed = stage["metadata"].get("isClosed", "false")
        print(f"  {stage['id']:<28} {stage['label']:<30} {closed}")

print("\nPaste the stage ids above into STAGE_LABELS in generate_data.py.")