"""
Rebuild ground truth from what actually landed in HubSpot.

Some contacts failed to upload (the ones with no email address). Deals tied to
them have no contact and no activity history, so the original ground truth
overcounts. Grading an agent against numbers that don't match the portal
produces false failures, which is worse than not grading at all.

Run after upload_data.py. Writes data/ground_truth_actual.json.

Run: python fix_ground_truth.py
"""

import csv
import json
from collections import Counter
from pathlib import Path

DATA = Path("data")
id_map = json.load(open("id_map.json"))
uploaded_contacts = set(id_map["contacts"])
uploaded_deals = set(id_map["deals"])

original = json.load(open(DATA / "ground_truth.json"))
MIN_CLOSED = original.get("min_closed_for_ranking", 12)


def load(name):
    return list(csv.DictReader(open(DATA / name)))


deals = [d for d in load("deals.csv") if d["deal_id"] in uploaded_deals]
engagements = [e for e in load("engagements.csv")
               if e["contact_id"] in uploaded_contacts]

OPEN_STAGES = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled",
               "decisionmakerboughtin", "contractsent"]

# Last activity per contact, from engagements that actually uploaded.
last_activity = {}
for e in engagements:
    days = int(e["days_ago"])
    cid = e["contact_id"]
    last_activity[cid] = min(last_activity.get(cid, 9999), days)

# A deal whose contact never uploaded has no activity at all. Exclude it
# rather than counting it as infinitely stale, because the agent can't see
# something that isn't there and shouldn't be marked wrong for missing it.
open_deals = [d for d in deals
              if d["stage"] in OPEN_STAGES
              and d["contact_id"] in uploaded_contacts]

stale = [d for d in open_deals if last_activity.get(d["contact_id"], 9999) >= 30]
dark = {d["contact_id"] for d in open_deals
        if last_activity.get(d["contact_id"], 9999) >= 60}

by_stage = {}
for stage in OPEN_STAGES:
    rows = [d for d in open_deals if d["stage"] == stage]
    by_stage[stage] = {"count": len(rows),
                       "value": sum(int(d["amount"]) for d in rows)}

channels = {}
for ch in {d["channel"] for d in deals}:
    closed = [d for d in deals if d["channel"] == ch and d["stage"].startswith("closed")]
    won = len([d for d in closed if d["stage"] == "closedwon"])
    channels[ch] = {"closed_deals": len(closed), "won": won,
                    "win_rate": round(won / len(closed), 3) if closed else None}

actual = {
    "note": "Recomputed from records that actually uploaded. Use this, not ground_truth.json.",
    "uploaded": {"contacts": len(uploaded_contacts), "deals": len(uploaded_deals)},
    "excluded_deals_no_contact": len([d for d in deals
                                      if d["contact_id"] not in uploaded_contacts]),
    "stale_deals_30d": {"count": len(stale),
                        "deal_ids": sorted(d["deal_id"] for d in stale)},
    "dark_contacts_60d_with_open_deal": {"count": len(dark),
                                         "contact_ids": sorted(dark)},
    "open_pipeline_by_stage": by_stage,
    "open_pipeline_total_value": sum(int(d["amount"]) for d in open_deals),
    "channel_performance": channels,
    "worst_channel": min((c for c in channels
                          if channels[c]["closed_deals"] >= MIN_CLOSED),
                         key=lambda c: channels[c]["win_rate"]),
}

with open(DATA / "ground_truth_actual.json", "w") as f:
    json.dump(actual, f, indent=2)

print(f"{'':22} original   actual")
print(f"  stale deals (30d)    {original['stale_deals_30d']['count']:>8}   "
      f"{actual['stale_deals_30d']['count']:>6}")
print(f"  dark contacts (60d)  {original['dark_contacts_60d_with_open_deal']['count']:>8}   "
      f"{actual['dark_contacts_60d_with_open_deal']['count']:>6}")
print(f"  open pipeline      ${original['open_pipeline_total_value']:>9,}  "
      f"${actual['open_pipeline_total_value']:>9,}")
print(f"  worst channel      {original['worst_channel']:>10}   {actual['worst_channel']:>6}")
print(f"\n  {actual['excluded_deals_no_contact']} deals excluded (contact never uploaded)")
print("\nGrade against data/ground_truth_actual.json from here on.")