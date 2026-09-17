# Benchmark: HubSpot official MCP server

Client: Claude Desktop (connector)
Endpoint: mcp.hubspot.com
Date: 2026-09-14

Graded on behavior, not counts: which fields the server reached for, whether
it queried engagement history, and whether results were repeatable.

## Q1: Which deals haven't moved in the last 30 days?
Tool calls: 5
Answer: Zero stale deals. Used hs_lastmodifieddate, which reads as today for
all imported records. Offered time-in-stage as an alternative.
MISS — wrong field. Never queried engagement history.

## Q2: Which deals are stalling and what should I say to each one? (first run)
Tool calls: 13
Answer: Declined to answer. Reported that close dates, last-activity and
last-contacted fields were all empty and most deals showed no associated
contacts. Offered three alternative approaches.
MISS — gave up. Never queried the notes.

## Q3: Give me the full picture on Allen PLC: deals, contacts, recent activity.
Tool calls: 5
Answer: Strong on structure. Returned 5 deals ($269K), 5 contacts with titles
and emails, and correct stages. "Recent activity" section reported only record
modification timestamps, then offered to pull real activity separately.
PARTIAL — complete on objects, empty on activity.

## Q4: Which acquisition channel is sending leads that don't close?
Tool calls: 21
Answer: Concluded the CRM has no usable channel data. Inspected
hs_analytics_source (all "Offline Sources / INTEGRATION") and attributed it to
a bulk import. Never found the custom acquisition_channel property.
MISS — highest tool count, confident wrong conclusion.
Caveat: discovering custom properties is genuinely hard without prior
knowledge. Partly a fair limitation.

## Q2 (repeat): Which deals are stalling and what should I say to each one?
Tool calls: 9
Answer: Pulled the 8 oldest open deals and wrote per-deal follow-ups. Noticed
that most stalls cluster immediately after buyer commitment (Decision Maker
Bought-In, Contract Sent) and called it a process problem rather than a sales
problem. Used deal createdate as the stall signal.
PARTIAL — good output, but still no engagement history read.

---

## Findings

**1. Engagement history was never read.**
Across 5 runs and ~53 tool calls, the server did not query a single one of the
2,942 backdated notes in the portal. It reached for hs_lastmodifieddate,
hs_analytics_source, and createdate, and repeatedly offered to check activity
"if pointed at specific deals." The data that answers "who has gone quiet" was
present and untouched throughout.

**2. Identical questions produced opposite outcomes.**
Q2 run one: 13 calls, no answer. Q2 run two: 9 calls, a useful answer with a
real insight. Same question, same tools, same data. The tool surface supplies
no strategy, so the agent improvises one per session and results vary. A rep
who gets nothing on Monday does not ask again on Tuesday.

**3. Object retrieval is solid. Cross-object reasoning is not.**
Q3 shows the pattern clearly: complete and well-organized on records, empty
on anything requiring a join to activity.

**4. Tool count rose as answers got worse.**
Q4 spent 21 calls to reach a wrong conclusion. Q1 spent 5 to reach the wrong
field. More retrieval did not mean more accuracy.

## Credit where due
- Hedged rather than fabricating; asked clarifying questions on Q1 and Q2.1
- Correctly diagnosed the data as an import in Q1 and Q4
- The Q2 repeat run produced follow-up copy that was usable as written