"""
GTM Agent Layer: an MCP server whose tools are shaped like questions.

The argument behind this file: a CRM already knows that a deal belongs to a
company, that the company has contacts, and that those contacts have activity
history. When tools are shaped like individual objects, the agent has to
reassemble those relationships at runtime, one fetch at a time. It's slow, it
buries the answer in raw records, and it can stop early without saying so.

So the assembly happens here instead, and the agent gets a complete answer.

Every tool returns a `summary` line with the finding already derived, so the
agent can answer without parsing the payload.

Run: python gtm_server.py
"""

import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

TOKEN = os.environ["HUBSPOT_TOKEN"]
BASE = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

mcp = FastMCP("gtm-agent-layer")

OPEN_STAGES = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled",
               "decisionmakerboughtin", "contractsent"]

STAGE_LABELS = {
    "appointmentscheduled": "Appointment Scheduled",
    "qualifiedtobuy": "Qualified To Buy",
    "presentationscheduled": "Presentation Scheduled",
    "decisionmakerboughtin": "Decision Maker Bought-In",
    "contractsent": "Contract Sent",
    "closedwon": "Closed Won",
    "closedlost": "Closed Lost",
}


# ---------------------------------------------------------------------------
# HubSpot helpers
# ---------------------------------------------------------------------------
def hs_get(path, **params):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def hs_post(path, payload):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()


def days_since(iso_string):
    """Days elapsed. Models reason about '34 days ago' far better than about
    2026-08-11T14:22:07.891Z."""
    if not iso_string:
        return None
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days


def relative(iso_string):
    d = days_since(iso_string)
    if d is None:
        return "unknown"
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def money(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def search_all(object_type, properties, filters=None, cap=5000):
    """Page through the search endpoint and return every matching record."""
    out, after = [], None
    while len(out) < cap:
        payload = {"properties": properties, "limit": 100}
        if filters:
            payload["filterGroups"] = [{"filters": filters}]
        if after:
            payload["after"] = after
        body = hs_post(f"/crm/v3/objects/{object_type}/search", payload)
        out.extend(body.get("results", []))
        after = body.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    return out


def batch_associations(from_type, to_type, ids):
    """{from_id: [to_id, ...]} for many records at once.

    The batch endpoint is what keeps these tools to a handful of HTTP calls
    instead of one per record.
    """
    result = {}
    for i in range(0, len(ids), 100):
        body = hs_post(f"/crm/v4/associations/{from_type}/{to_type}/batch/read",
                       {"inputs": [{"id": str(x)} for x in ids[i:i + 100]]})
        for row in body.get("results", []):
            src = str(row["from"]["id"])
            result[src] = [str(t["toObjectId"]) for t in row.get("to", [])]
    return result


def batch_read(object_type, ids, properties):
    if not ids:
        return []
    out = []
    ids = list(ids)
    for i in range(0, len(ids), 100):
        body = hs_post(f"/crm/v3/objects/{object_type}/batch/read",
                       {"inputs": [{"id": str(x)} for x in ids[i:i + 100]],
                        "properties": properties})
        out.extend(body.get("results", []))
    return out


def associated_ids(from_type, record_id, to_type):
    try:
        body = hs_get(f"/crm/v4/objects/{from_type}/{record_id}/associations/{to_type}",
                      limit=100)
        return [r["toObjectId"] for r in body.get("results", [])]
    except requests.HTTPError:
        return []


# ---------------------------------------------------------------------------
# Activity index
#
# "Has this gone quiet" is the question object-shaped tools never answer,
# because it needs every note joined back to every contact. Building that
# index costs a handful of batched calls, so it's cached briefly: a user
# asking three pipeline questions in a row shouldn't pay for it three times.
# ---------------------------------------------------------------------------
_activity_cache = {"built_at": 0, "by_contact": {}}
CACHE_TTL = 300  # seconds


def contact_last_touch(force=False):
    """{contact_id: days_since_last_note}."""
    if not force and time.time() - _activity_cache["built_at"] < CACHE_TTL:
        return _activity_cache["by_contact"]

    notes = search_all("notes", ["hs_timestamp"])
    note_days = {n["id"]: days_since(n["properties"].get("hs_timestamp"))
                 for n in notes}

    links = batch_associations("notes", "contacts", list(note_days))
    by_contact = {}
    for note_id, contact_ids in links.items():
        d = note_days.get(note_id)
        if d is None:
            continue
        for cid in contact_ids:
            if cid not in by_contact or d < by_contact[cid]:
                by_contact[cid] = d

    _activity_cache.update(built_at=time.time(), by_contact=by_contact)
    return by_contact


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool
def lead_context(email: str) -> dict:
    """Everything known about one lead, assembled in a single call.

    Returns the contact record, their company, every deal they're attached to
    (open and closed), and their full engagement history with how long ago
    each touch happened.

    Use this whenever a question is about a specific person or account:
    "what's the story with sarah@acme.com", "should I follow up with this
    lead", "give me the full picture before my call". It replaces the
    sequence of searching for a contact, then fetching their company, then
    their deals, then their activity.

    Takes an email address. Returns an error field if no contact matches.
    """
    found = hs_post("/crm/v3/objects/contacts/search", {
        "filterGroups": [{"filters": [
            {"propertyName": "email", "operator": "EQ", "value": email}
        ]}],
        "properties": ["email", "firstname", "lastname", "jobtitle",
                       "acquisition_channel", "createdate"],
        "limit": 1,
    })

    if not found.get("results"):
        return {"error": f"No contact found with email {email}"}

    contact = found["results"][0]
    cid = contact["id"]
    p = contact["properties"]

    company = None
    company_ids = associated_ids("contacts", cid, "companies")
    if company_ids:
        rows = batch_read("companies", company_ids[:1],
                          ["name", "domain", "industry", "numberofemployees", "city"])
        if rows:
            cp = rows[0]["properties"]
            company = {"name": cp.get("name"), "domain": cp.get("domain"),
                       "industry": cp.get("industry"),
                       "employees": cp.get("numberofemployees"),
                       "city": cp.get("city")}

    deal_ids = associated_ids("contacts", cid, "deals")
    deal_rows = batch_read("deals", deal_ids,
                           ["dealname", "amount", "dealstage", "createdate",
                            "acquisition_channel"])
    deals = []
    for row in deal_rows:
        dp = row["properties"]
        stage = dp.get("dealstage")
        deals.append({"name": dp.get("dealname"), "amount": dp.get("amount"),
                      "stage": STAGE_LABELS.get(stage, stage),
                      "is_open": stage in OPEN_STAGES,
                      "age": relative(dp.get("createdate"))})
    deals.sort(key=lambda d: (not d["is_open"], d["name"] or ""))

    note_ids = associated_ids("contacts", cid, "notes")
    note_rows = batch_read("notes", note_ids, ["hs_note_body", "hs_timestamp"])
    notes = sorted(
        ({"when": relative(n["properties"].get("hs_timestamp")),
          "days_ago": days_since(n["properties"].get("hs_timestamp")) or 9999,
          "body": (n["properties"].get("hs_note_body") or "")[:200]}
         for n in note_rows),
        key=lambda n: n["days_ago"])

    last_touch = notes[0]["days_ago"] if notes else None
    open_deals = [d for d in deals if d["is_open"]]
    name = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip()

    return {
        "contact": {"name": name, "email": p.get("email"),
                    "title": p.get("jobtitle"),
                    "channel": p.get("acquisition_channel"),
                    "in_crm_since": relative(p.get("createdate"))},
        "company": company,
        "deals": deals,
        "engagement": {"total_touches": len(notes),
                       "last_touch": f"{last_touch} days ago" if last_touch is not None else "never",
                       "recent": notes[:10]},
        "summary": (
            f"{name} at {company['name'] if company else 'unknown company'}. "
            f"{len(open_deals)} open deal(s), {len(deals)} total. "
            f"Last contact {last_touch} days ago."
            if last_touch is not None else
            f"{name}. No recorded activity."),
    }


@mcp.tool
def find_stale_deals(days: int = 30, limit: int = 25) -> dict:
    """Open deals where nobody has talked to the contact in N days.

    Staleness is measured from real engagement history (logged notes, calls,
    emails), not from when the record was last edited. Those are different
    questions and only the first one tells you whether a deal is going cold.

    Every returned deal already carries its contact, company, value, stage,
    and days since last touch, so no follow-up lookups are needed to write
    outreach.

    Use for: "which deals are stalling", "what's gone quiet", "who needs a
    follow-up", "which deals haven't moved". Returns the full count plus the
    oldest `limit` deals.
    """
    deals = search_all("deals", ["dealname", "amount", "dealstage", "createdate",
                                 "acquisition_channel"],
                       filters=[{"propertyName": "dealstage", "operator": "IN",
                                 "values": OPEN_STAGES}])
    if not deals:
        return {"stale_count": 0, "deals": [], "summary": "No open deals found."}

    deal_ids = [d["id"] for d in deals]
    to_contacts = batch_associations("deals", "contacts", deal_ids)
    to_companies = batch_associations("deals", "companies", deal_ids)
    last_touch = contact_last_touch()

    contact_ids = {c for v in to_contacts.values() for c in v}
    contact_rows = batch_read("contacts", contact_ids,
                              ["firstname", "lastname", "email", "jobtitle"])
    contacts = {r["id"]: r["properties"] for r in contact_rows}

    company_ids = {c for v in to_companies.values() for c in v}
    company_rows = batch_read("companies", company_ids, ["name"])
    companies = {r["id"]: r["properties"].get("name") for r in company_rows}

    stale, no_activity = [], 0
    for d in deals:
        dp = d["properties"]
        cids = to_contacts.get(d["id"], [])
        quiet = min((last_touch.get(c, 9999) for c in cids), default=9999)

        if quiet < days:
            continue
        if quiet == 9999:
            no_activity += 1

        c = contacts.get(cids[0], {}) if cids else {}
        comp_ids = to_companies.get(d["id"], [])
        stale.append({
            "deal": dp.get("dealname"),
            "amount": money(dp.get("amount")),
            "stage": STAGE_LABELS.get(dp.get("dealstage"), dp.get("dealstage")),
            "company": companies.get(comp_ids[0]) if comp_ids else None,
            "contact": f"{c.get('firstname', '')} {c.get('lastname', '')}".strip() or None,
            "email": c.get("email"),
            "title": c.get("jobtitle"),
            "days_since_contact": None if quiet == 9999 else quiet,
            "channel": dp.get("acquisition_channel"),
            "deal_age": relative(dp.get("createdate")),
        })

    stale.sort(key=lambda x: x["days_since_contact"] or 99999, reverse=True)
    value = sum(s["amount"] for s in stale)

    return {
        "threshold_days": days,
        "stale_count": len(stale),
        "open_deals_checked": len(deals),
        "value_at_risk": value,
        "with_no_recorded_activity": no_activity,
        "deals": stale[:limit],
        "summary": (f"{len(stale)} of {len(deals)} open deals have had no contact "
                    f"in {days}+ days, worth ${value:,}. Showing the "
                    f"{min(limit, len(stale))} quietest."),
    }


@mcp.tool
def pipeline_health(include_closed: bool = False) -> dict:
    """Open pipeline broken down by stage: deal count, value, and average age.

    Returns stages in pipeline order with totals, so the shape of the funnel
    is visible without any arithmetic.

    Use for: "what's my pipeline worth", "how's the pipeline looking",
    "where are deals concentrated", "pipeline by stage". Set include_closed
    to also get won and lost totals.
    """
    stages = OPEN_STAGES + (["closedwon", "closedlost"] if include_closed else [])
    deals = search_all("deals", ["dealname", "amount", "dealstage", "createdate"],
                       filters=[{"propertyName": "dealstage", "operator": "IN",
                                 "values": stages}])

    by_stage = {}
    for s in stages:
        rows = [d for d in deals if d["properties"].get("dealstage") == s]
        ages = [days_since(d["properties"].get("createdate")) for d in rows]
        ages = [a for a in ages if a is not None]
        by_stage[STAGE_LABELS[s]] = {
            "deals": len(rows),
            "value": sum(money(d["properties"].get("amount")) for d in rows),
            "avg_age_days": round(sum(ages) / len(ages)) if ages else None,
        }

    open_rows = [d for d in deals if d["properties"].get("dealstage") in OPEN_STAGES]
    open_value = sum(money(d["properties"].get("amount")) for d in open_rows)

    biggest = max(((k, v) for k, v in by_stage.items()
                   if k in [STAGE_LABELS[s] for s in OPEN_STAGES]),
                  key=lambda kv: kv[1]["value"], default=(None, None))

    return {
        "by_stage": by_stage,
        "open_deals": len(open_rows),
        "open_pipeline_value": open_value,
        "summary": (f"{len(open_rows)} open deals worth ${open_value:,}. "
                    f"Most value sits in {biggest[0]} "
                    f"(${biggest[1]['value']:,})." if biggest[0] else
                    f"{len(open_rows)} open deals worth ${open_value:,}."),
    }


@mcp.tool
def segment_performance(dimension: str = "acquisition_channel",
                        min_closed: int = 12) -> dict:
    """Win rate by segment, computed from closed deals only.

    Groups closed-won and closed-lost deals by a deal property and returns
    the conversion rate for each, sorted worst first. Segments below
    min_closed are reported but excluded from the best/worst call, because a
    channel with four closed deals can look catastrophic on noise alone.

    Use for: "which channel sends leads that don't close", "where is our
    lead quality worst", "how do sources compare", "which segment converts".

    dimension defaults to acquisition_channel. Any deal property works.
    """
    deals = search_all("deals", [dimension, "amount", "dealstage"],
                       filters=[{"propertyName": "dealstage", "operator": "IN",
                                 "values": ["closedwon", "closedlost"]}])

    groups = {}
    for d in deals:
        key = d["properties"].get(dimension) or "(not set)"
        g = groups.setdefault(key, {"closed": 0, "won": 0, "won_value": 0})
        g["closed"] += 1
        if d["properties"].get("dealstage") == "closedwon":
            g["won"] += 1
            g["won_value"] += money(d["properties"].get("amount"))

    rows = []
    for key, g in groups.items():
        rows.append({
            "segment": key,
            "closed_deals": g["closed"],
            "won": g["won"],
            "win_rate": round(g["won"] / g["closed"], 3) if g["closed"] else None,
            "revenue_won": g["won_value"],
            "enough_volume": g["closed"] >= min_closed,
        })
    rows.sort(key=lambda r: r["win_rate"] if r["win_rate"] is not None else 1)

    ranked = [r for r in rows if r["enough_volume"]]
    worst = ranked[0] if ranked else None
    best = ranked[-1] if ranked else None

    if worst and best:
        summary = (f"{worst['segment']} converts worst at "
                   f"{worst['win_rate']:.1%} ({worst['won']}/{worst['closed_deals']}). "
                   f"{best['segment']} is strongest at {best['win_rate']:.1%}. "
                   f"Segments under {min_closed} closed deals excluded from ranking.")
    else:
        summary = f"Not enough closed deals to rank {dimension} reliably."

    return {
        "dimension": dimension,
        "min_closed_for_ranking": min_closed,
        "segments": rows,
        "worst": worst["segment"] if worst else None,
        "best": best["segment"] if best else None,
        "summary": summary,
    }


if __name__ == "__main__":
    mcp.run()