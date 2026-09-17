# Comparison: official HubSpot MCP server vs. GTM Agent Layer

Same portal. Same questions. Same client. Both speak MCP, both read the
HubSpot API. The difference is tool design.

| Question | Official | GTM Agent Layer |
|---|---|---|
| Deals with no activity in 30 days | 7 calls → **0 found** | 2 calls → **112 found** |
| Which deals are stalling, and what to say | 13 calls → **gave up** | 3 calls → **6 tailored follow-ups** |
| Which channel sends leads that don't close | 21 calls → **"no channel data"** | 2 calls → **paid_social, 3.4%** |
| Full picture on a company by name | 5 calls → **complete on records** | 1 call → **could not answer** |

## What the numbers show

**More retrieval did not mean more accuracy.** The official server's worst
answer took its most calls: 21 lookups to conclude the CRM had no channel
data. It was reading HubSpot's built-in traffic source field. The channel
lived in a custom property it never found.

**2,942 notes were never read.** Across five runs and roughly 53 tool calls,
the official server never queried the engagement history. It reached for
hs_lastmodifieddate, then hs_analytics_source, then createdate, and
repeatedly offered to check activity "if pointed at specific deals." The data
that answers "who has gone quiet" sat untouched throughout.

**The same question produced opposite outcomes.** Asked twice in separate
sessions, the official server first spent 13 calls and declined to answer,
then spent 9 and produced something useful. Same question, same tools, same
data. Object-shaped tools supply no strategy, so the agent improvises one per
session. A rep who gets nothing on Monday does not ask again on Tuesday.

## Where the official server won

Company-level lookup. Asked about Allen PLC by name, it returned five deals,
five contacts with titles and emails, and correct stages in five calls. The
custom server has no company-level entry point and had to ask for an email.

Its object retrieval is solid. The gap is in cross-object reasoning, which is
where most real questions live.

## What this is not

Not a criticism of MCP. Both servers use the protocol and it works fine. The
finding is about how tools are shaped, not about the plug they use.

Not a claim that generic tools are useless. They handle single-object
questions well. They struggle when a question needs a join, which is most of
the time in go-to-market work.