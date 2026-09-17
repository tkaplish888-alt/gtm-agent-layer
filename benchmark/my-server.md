# Benchmark: GTM Agent Layer (custom MCP server)

Client: Claude Desktop (local stdio server)
Portal: same HubSpot test portal as the official-server run
Date: 2026-09-17

Both servers speak MCP and both read the same HubSpot API. The only
difference is how the tools are shaped. HubSpot connector disabled during
this run so only these tools could answer.

## Q1: Which deals have had no activity in the last 30 days?
Tool calls: 2
Answer: 112 of 218 open deals quiet for 30+ days, $3.68M at risk. Returned
the 10 oldest with company, contact name, title, value, stage, and days
silent. Longest gap 313 days.
HIT — measured from engagement history, not record modification.

## Q2: Which deals are stalling and what should I say to each one?
Tool calls: 3
Answer: Same 112, then six tailored follow-ups. Ranked by silence and deal
value. Noticed that Contract Sent stalls point to internal buyer friction
rather than lost interest. Adjusted tone by role and channel: low-pressure
for the referral lead, sharp and value-forward for the CTO.
HIT — none of that reasoning is in the tool code. It came from having
complete context in one payload.

## Q3: Give me the full picture on Allen PLC: deals, contacts, recent activity.
Tool calls: 1 (tool search only)
Answer: Could not answer. lead_context takes an email address; there is no
company-level lookup. Asked for a contact email instead.
MISS — a real gap. The official server handled this one cleanly. A
company_context tool would close it; logged rather than patched so the
comparison stays honest.

## Q4: Which acquisition channel is sending leads that don't close?
Tool calls: 2
Answer: paid_social at 3.4% (1 win from 29 closed), against referral at 32%
and organic/paid search in the high 20s. Flagged it as an outlier rather
than ordinary underperformance.
HIT — reads a custom property the official server never discovered.

---

## Notes on the numbers

**112 vs. 109 in ground truth.** Ground truth is computed when the data is
generated; the staleness threshold moves with the clock. Eight deals sit in
the 30-to-32-day band, so the count drifts about three per day. Not a
discrepancy, a moving boundary.

**Deal age vs. contact silence.** The generator assigns deal creation dates
and note timestamps independently, so a few rows show a recent deal with a
long-silent contact. The staleness measure is correct; the synthetic data is
inconsistent in those cases.

## Design decisions behind the results

**Engagement history is never optional.** Every tool that touches staleness
joins notes to contacts to deals. This is the single difference that produced
112 instead of 0 on Q1.

**Thin segments are not ranked.** segment_performance reports every segment
but excludes anything under 12 closed deals from the best/worst call. A
channel with four closed deals can look catastrophic on noise alone.

**Dates are relative, stages are labels.** "34 days ago" instead of an ISO
timestamp. "Qualified To Buy" instead of qualifiedtobuy. The consumer is a
language model, so the payload is written for one.

**Every response carries a summary line** with the finding already derived,
so the agent can answer without parsing the payload.