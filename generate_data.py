"""
Synthetic CRM data generator.

Produces companies, contacts, deals, and engagements for a HubSpot test portal,
plus a ground_truth.json file recording the correct answers to the benchmark
questions. The ground truth is the point: it's how we grade whether an AI
agent found everything it should have.

Design note: this data is deliberately imperfect. Real CRMs have missing
emails, duplicate people, and channels that quietly underperform. Clean
synthetic data would make the agent's job artificially easy and the
benchmark meaningless.

Run: python generate_data.py
"""

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

# Seeded so every run produces identical data. If the benchmark is going to
# mean anything, the dataset has to be reproducible.
SEED = 42
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

TODAY = datetime(2026, 9, 13)
OUT = Path("data")
OUT.mkdir(exist_ok=True)

N_COMPANIES = 120
N_CONTACTS = 600
N_DEALS = 400  # see MIN_CLOSED_FOR_RANKING below: channel win rates need volume

# A channel needs at least this many closed deals before we'll call it the
# worst performer. Without the floor, a channel with 3 closed deals and 0 wins
# ranks below the one we actually planted, and the benchmark question stops
# having a defensible answer.
MIN_CLOSED_FOR_RANKING = 12

# ---------------------------------------------------------------------------
# Channel design
#
# paid_social is the planted underperformer. It sends plenty of volume and
# closes badly. A good analysis should surface this; it's one of the
# benchmark questions.
# ---------------------------------------------------------------------------
CHANNELS = {
    "organic_search": {"weight": 0.26, "win_rate": 0.28},
    "referral":       {"weight": 0.14, "win_rate": 0.34},
    "webinar":        {"weight": 0.16, "win_rate": 0.26},
    "event":          {"weight": 0.10, "win_rate": 0.24},
    "paid_search":    {"weight": 0.16, "win_rate": 0.25},
    "paid_social":    {"weight": 0.18, "win_rate": 0.05},  # the problem child
}

# HubSpot's `industry` property is an enumeration, not free text. These are
# exact enum values, copied from what the API reported as allowed. Invent a
# friendly label here and the entire batch of 100 is rejected.
INDUSTRIES = [
    "COMPUTER_SOFTWARE",
    "FINANCIAL_SERVICES",
    "HEALTH_WELLNESS_AND_FITNESS",
    "HIGHER_EDUCATION",
    "INTERNET",
    "COMPUTER_NETWORK_SECURITY",
    "CAPITAL_MARKETS",
    "ELECTRICAL_ELECTRONIC_MANUFACTURING",
]

# ---------------------------------------------------------------------------
# Pipeline stages
#
# These are HubSpot's INTERNAL stage IDs for the default sales pipeline, not
# display labels. The API accepts "appointmentscheduled", never "Appointment
# Scheduled" and never a friendly name of your own invention. Pass something
# it doesn't recognize and the whole batch is rejected, not just that record.
#
# Do not trust this list blindly. Stage IDs are per-pipeline and custom
# pipelines use generated numeric IDs. Run check_pipeline.py against your own
# portal first and paste in what it returns.
# ---------------------------------------------------------------------------
STAGE_LABELS = {
    "appointmentscheduled":   "Appointment Scheduled",
    "qualifiedtobuy":         "Qualified To Buy",
    "presentationscheduled":  "Presentation Scheduled",
    "decisionmakerboughtin":  "Decision Maker Bought-In",
    "contractsent":           "Contract Sent",
    "closedwon":              "Closed Won",
    "closedlost":             "Closed Lost",
}

OPEN_STAGES = [
    "appointmentscheduled",
    "qualifiedtobuy",
    "presentationscheduled",
    "decisionmakerboughtin",
    "contractsent",
]
ALL_STAGES = OPEN_STAGES + ["closedwon", "closedlost"]

OWNERS = ["Priya Raman", "Marcus Webb", "Danielle Ortiz", "Sam Okafor"]

ENGAGEMENT_TYPES = ["email", "call", "meeting", "note"]


def pick_channel():
    names = list(CHANNELS)
    weights = [CHANNELS[c]["weight"] for c in names]
    return random.choices(names, weights=weights)[0]


def days_ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
companies = []
for i in range(N_COMPANIES):
    name = fake.company()
    domain = name.lower().replace(",", "").replace(".", "").replace(" ", "")[:20] + ".com"
    companies.append({
        "company_id": f"C{i:04d}",
        "name": name,
        "domain": domain,
        "industry": random.choice(INDUSTRIES),
        "employee_count": random.choice([12, 45, 90, 180, 400, 850, 2200, 5000]),
        "city": fake.city(),
    })

# ---------------------------------------------------------------------------
# Contacts
#
# Two imperfections introduced here:
#   1. ~8% have no email at all. Common in real CRMs from event list imports
#      and partial form fills. Breaks naive joins.
#   2. 12 duplicates: same human, two records, different domain. Happens when
#      someone fills a form with a personal address after a work address.
# ---------------------------------------------------------------------------
contacts = []
for i in range(N_CONTACTS):
    company = random.choice(companies)
    first, last = fake.first_name(), fake.last_name()

    if random.random() < 0.08:
        email = ""  # no email on file
    else:
        email = f"{first.lower()}.{last.lower()}@{company['domain']}"

    contacts.append({
        "contact_id": f"P{i:04d}",
        "first_name": first,
        "last_name": last,
        "email": email,
        "job_title": random.choice([
            "VP Marketing", "Director of Ops", "Head of Growth", "CTO",
            "Marketing Manager", "Analyst", "COO", "Demand Gen Lead",
        ]),
        "company_id": company["company_id"],
        "channel": pick_channel(),
        "created_days_ago": random.randint(5, 400),
    })

# Duplicates: clone 12 contacts under a personal email domain.
duplicate_sources = random.sample([c for c in contacts if c["email"]], 12)
for j, src in enumerate(duplicate_sources):
    dup = dict(src)
    dup["contact_id"] = f"P9{j:03d}"
    dup["email"] = f"{src['first_name'].lower()}{src['last_name'].lower()}@gmail.com"
    dup["created_days_ago"] = max(1, src["created_days_ago"] - random.randint(10, 120))
    contacts.append(dup)

contacts_by_id = {c["contact_id"]: c for c in contacts}

# ---------------------------------------------------------------------------
# Deals
#
# Deal age spans 2 to 270 days so stale detection has real signal. Win rate
# is driven by the originating contact's channel, which is what makes the
# channel analysis question answerable.
# ---------------------------------------------------------------------------
deals = []
contact_pool = random.sample(contacts, N_DEALS)

for i, contact in enumerate(contact_pool):
    age = random.choice([
        random.randint(2, 20),     # fresh
        random.randint(21, 60),    # mid
        random.randint(61, 150),   # aging
        random.randint(151, 270),  # very old
    ])
    channel = contact["channel"]
    win_rate = CHANNELS[channel]["win_rate"]

    # Older deals are more likely to have resolved one way or the other.
    if age > 90:
        closed = random.random() < 0.8
    elif age > 45:
        closed = random.random() < 0.45
    else:
        closed = random.random() < 0.12

    if closed:
        stage = "closedwon" if random.random() < win_rate else "closedlost"
    else:
        stage = random.choice(OPEN_STAGES)

    deals.append({
        "deal_id": f"D{i:04d}",
        "name": f"{contacts_by_id[contact['contact_id']]['first_name']}'s team - "
                f"{random.choice(['Pilot', 'Annual', 'Expansion', 'Renewal'])}",
        "amount": random.choice([4500, 9000, 15000, 24000, 38000, 60000, 95000]),
        "stage": stage,                      # send this to HubSpot as dealstage
        "stage_label": STAGE_LABELS[stage],   # for your own reading only
        "contact_id": contact["contact_id"],
        "company_id": contact["company_id"],
        "owner": random.choice(OWNERS),
        "channel": channel,
        "created_days_ago": age,
    })

# ---------------------------------------------------------------------------
# Engagements
#
# Long tail on purpose: most contacts have one or two touches, a handful have
# twenty. Uniform engagement would be fiction, and it would also make "who
# has gone quiet" trivially easy.
# ---------------------------------------------------------------------------
engagements = []
eng_id = 0
last_activity = {}  # contact_id -> days since last touch

for contact in contacts:
    roll = random.random()
    if roll < 0.55:
        n = random.randint(1, 2)
    elif roll < 0.88:
        n = random.randint(3, 7)
    else:
        n = random.randint(12, 22)

    max_age = min(contact["created_days_ago"], 365)
    touch_days = sorted(
        [random.randint(0, max_age) for _ in range(n)], reverse=True
    )

    for d in touch_days:
        engagements.append({
            "engagement_id": f"E{eng_id:05d}",
            "contact_id": contact["contact_id"],
            "type": random.choice(ENGAGEMENT_TYPES),
            "days_ago": d,
            "timestamp": days_ago(d),
            "summary": random.choice([
                "Discussed pricing and timeline",
                "Left voicemail, no response",
                "Sent follow-up deck",
                "Demo completed, positive signal",
                "Asked about security review",
                "Reschedule requested",
            ]),
        })
        eng_id += 1

    last_activity[contact["contact_id"]] = min(touch_days) if touch_days else 999

# ---------------------------------------------------------------------------
# Ground truth
#
# This is the file that makes the benchmark possible. Without it you have no
# way to tell whether an agent's confident-sounding answer was complete.
# ---------------------------------------------------------------------------
open_deals = [d for d in deals if d["stage"] in OPEN_STAGES]

stale_deals = [
    d for d in open_deals
    if last_activity.get(d["contact_id"], 999) >= 30
]

dark_contacts = [
    d["contact_id"] for d in open_deals
    if last_activity.get(d["contact_id"], 999) >= 60
]

pipeline_by_stage = {}
for stage in OPEN_STAGES:
    stage_deals = [d for d in open_deals if d["stage"] == stage]
    pipeline_by_stage[stage] = {
        "label": STAGE_LABELS[stage],
        "count": len(stage_deals),
        "value": sum(d["amount"] for d in stage_deals),
    }

channel_performance = {}
for ch in CHANNELS:
    ch_deals = [d for d in deals if d["channel"] == ch and d["stage"].startswith("closed")]
    won = len([d for d in ch_deals if d["stage"] == "closedwon"])
    total = len(ch_deals)
    channel_performance[ch] = {
        "closed_deals": total,
        "won": won,
        "win_rate": round(won / total, 3) if total else None,
    }

ground_truth = {
    "generated_at": TODAY.isoformat(),
    "seed": SEED,
    "totals": {
        "companies": len(companies),
        "contacts": len(contacts),
        "deals": len(deals),
        "engagements": len(engagements),
        "open_deals": len(open_deals),
    },
    "contacts_missing_email": len([c for c in contacts if not c["email"]]),
    "duplicate_contact_ids": [c["contact_id"] for c in contacts if c["contact_id"].startswith("P9")],
    "stale_deals_30d": {
        "count": len(stale_deals),
        "deal_ids": sorted(d["deal_id"] for d in stale_deals),
    },
    "dark_contacts_60d_with_open_deal": {
        "count": len(set(dark_contacts)),
        "contact_ids": sorted(set(dark_contacts)),
    },
    "open_pipeline_by_stage": pipeline_by_stage,
    "open_pipeline_total_value": sum(d["amount"] for d in open_deals),
    "channel_performance": channel_performance,
    "worst_channel": min(
        (c for c in channel_performance
         if channel_performance[c]["closed_deals"] >= MIN_CLOSED_FOR_RANKING),
        key=lambda c: channel_performance[c]["win_rate"],
    ),
    "min_closed_for_ranking": MIN_CLOSED_FOR_RANKING,
}

# ---------------------------------------------------------------------------
# Write everything out
# ---------------------------------------------------------------------------
def write_csv(rows, filename):
    path = OUT / filename
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


write_csv(companies, "companies.csv")
write_csv(contacts, "contacts.csv")
write_csv(deals, "deals.csv")
write_csv(engagements, "engagements.csv")

with open(OUT / "ground_truth.json", "w") as f:
    json.dump(ground_truth, f, indent=2)

print(f"Companies:   {len(companies)}")
print(f"Contacts:    {len(contacts)} ({ground_truth['contacts_missing_email']} missing email, "
      f"{len(ground_truth['duplicate_contact_ids'])} duplicates)")
print(f"Deals:       {len(deals)} ({len(open_deals)} open)")
print(f"Engagements: {len(engagements)}")
print()
print("GROUND TRUTH")
print(f"  Stale deals (30d, open):        {ground_truth['stale_deals_30d']['count']}")
print(f"  Dark contacts (60d, open deal): {ground_truth['dark_contacts_60d_with_open_deal']['count']}")
print(f"  Open pipeline value:            ${ground_truth['open_pipeline_total_value']:,}")
print(f"  Worst channel:                  {ground_truth['worst_channel']} "
      f"({channel_performance[ground_truth['worst_channel']]['win_rate']:.1%} win rate)")
print()
print("OPEN PIPELINE BY STAGE")
for stage, info in pipeline_by_stage.items():
    print(f"  {info['label']:<26} {info['count']:>3} deals   ${info['value']:>9,}")
print()
print(f"Written to {OUT.resolve()}/")