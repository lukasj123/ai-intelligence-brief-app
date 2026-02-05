# AI News Briefings

An automated pipeline that reads AI news from 40+ sources (RSS feeds + Gmail newsletters), uses LLMs to extract and verify factual claims, then synthesizes everything into a concise executive briefing sent via email.

## What it does

I wanted personalized AI news briefings without the noise. The system:

1. **Ingests** news from RSS feeds and Gmail newsletters
2. **Extracts** factual claims using GPT-4o-mini
3. **Verifies** claims by checking if sources contradict each other
4. **Synthesizes** everything into a short briefing with source citations
5. **Delivers** via email on a schedule (I run it daily)

## Screenshot of a daily brief

<img width="1085" height="760" alt="Screenshot 2026-02-05 at 10 02 32 AM" src="https://github.com/user-attachments/assets/4172f1b3-927c-4038-a881-4ca73fa289e9" />

## Why I built this

It's difficult to keep my finger on the pulse of what's happening in the world regarding AI news and developments. It's such a quickly changing landscape, so I decided I might as well use AI to stay on top of AI. I created a burner Gmail account solely to subscribe to AI-related newsletters. I wanted:

- **One briefing** instead of 50 emails
- **Source diversity** (not just what one publication thinks is important)
- **Transparency** (show me when sources disagree)
- **Control** (customize what gets prioritized)

Traditional news aggregators may just sort by recency, and they aren't customized to my preferences. This one synthesizes claims, detects when sources contradict each other, and prioritizes by importance rather than publish time. Plus I can configure custom instructions.

## Quick start

**Install:**
```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
```

**Set up Gmail OAuth** (for reading newsletters and sending briefings):
1. Download OAuth credentials from Google Cloud Console
2. Save as `.credentials/gmail_credentials.json`
3. Run `python -m ingest.gmail` once to authorize

**Run the full pipeline:**
```bash
python briefing_pipeline.py
```

**Or use the Streamlit UI:**
```bash
streamlit run ui/control.py
```

## How it works

The pipeline has 5 LLM stages (all using gpt-4o-mini to keep costs low):

### 1. Publisher extraction (Gmail only)
Gmail newsletters often have generic sender addresses. I use regex + LLM to identify the actual publisher (e.g., "Import AI" instead of "no-reply@substack.com"). Publisher results are cached, so if the program encounters a source it's already extracted the publisher from, it requires much fewer resources.

### 2. Claim extraction
The LLM reads articles and extracts factual claims with these confidence labels:
- **reported**: directly stated
- **inferred**: implied but not explicit
- **speculative**: predictions or opinions

It also assigns topic IDs to group related claims together. This happens in batches of 50 articles to avoid rate limits.

### 3. Topic normalization
Sometimes the LLM creates slightly different topic IDs for the same thing (e.g., "gpt5_release" and "openai_gpt5_launch"). A second LLM call merges these into normalized topics.

### 4. Verification

For each claim, the program collects all other articles on the same topic. If a claim appears in multiple sources, its confidence level is deterministically upgraded to corroborated. 

However, it is more difficult to deterministically program contestation detection, so an LLM reviews the claim language to detect if any sources contradict or dispute one another. If they do, the claim confidence level is downgraded to contested.

This is way simpler than trying to fact-check against some external truth database. I just want to know when my sources disagree. I found implementing this hybrid approach of deterministic + LLM reasoning to be an interesting exercise, and I imagine more workflows like this are the future of coding.

### 5. Review
The final LLM call synthesizes everything into a briefing with:
- A headline
- 2-3 sentence summary
- Up to 25 (configurable) key points with source citations.*

It's instructed to prioritize important developments (not just recent ones) and diversify sources (avoid over-relying on one publisher).

*Due to the nature of the sources (for example, HTML parsed from email bodies), it is inherently difficult to extract URLs to point to the source material. I tried to get this to work, but ultimately, I opted to just write the source citation as plaintext. I would love ideas for improvement here!

## Configuration

Everything is configured in `config/config.yaml` - single source of truth:

```yaml
# LLM Analysis Settings
analyzer_instructions: "Focus on concrete technical developments, product releases, and policy changes."
reviewer_focus: "Prioritize highly relevant AI developments."
max_key_points: 10

# Ingestion Settings
frequency: "weekly"  # daily, weekly, biweekly, monthly
lookback_days: 7  # Override calculated from frequency
skip_normalization: false

# Email Delivery
email:
  enabled: true
  recipient_email: "you@example.com"
  send_day: "Monday"
  send_time: "09:00"
```

You can also use the **Streamlit control panel** to configure everything via UI:
```bash
streamlit run ui/control.py
```

**Add RSS feeds** in `config/rss_feeds.yaml`:
```yaml
"OpenAI":
  url: "https://openai.com/blog/rss/"
  type: frontier_lab
```

The `type` field controls whether the system fetches full article text or uses the RSS content directly. See `core/ingestion_policy.py` for the policy rules governing the types.

## Cost control

LLM costs add up fast if you're not careful. The system has several safeguards:

- Hard limit: 200 articles per run
- Content truncation: 10,000 chars per article max
- Warnings if estimated cost > $0.50
- Email alert if cost > $1.00
- All costs logged to `logs/costs.jsonl`

A typical run with 200 articles costs just several cents, if that, usually.

## Source types

Different sources have different RSS feed formats and incentives. I categorize them:

- **news** (FT, Bloomberg, STAT): Fetch full articles from web
- **corporate_research** (Microsoft, Amazon): RSS already has full content
- **frontier_lab** (OpenAI, DeepMind): Short snippets, use RSS directly
- **press_release** (FDA, FTC, NIST): Government announcements
- **policy_org** (EFF, Brookings): Think tanks and NGOs
- **analysis_newsletter** (SemiAnalysis, Stratechery): Expert analysis

The type determines whether we fetch the full article or trust the RSS content. This is configured in `core/ingestion_policy.py` and was tuned based on empirical analysis of actual RSS feed data.

## What I learned

**Topic-scoped verification works better than global fact-checking.** Initially I tried to verify every claim against all sources. This created a mess - too many false positives for contested. Adding the topics forced the LLM to evaluate claims 

**Batching is essential.** OpenAI's rate limits will kill you if you send 100 articles in one API call. Batching into chunks of 50 keeps things under the 200k tokens-per-minute limit.

**RSS feeds are inconsistent.** Some publishers include full articles in their RSS feeds. Others just put a headline and snippet. Some put nothing at all. I had to build a tiered ingestion policy to handle this.

**Caching saves money.** Publisher extraction from Gmail newsletters could get expensive, but caching by email address means you only pay once per newsletter you subscribe to.

**LLMs make mistakes.** The review stage sometimes includes claims marked as "Unknown Source" even though I explicitly tell it not to. I added post-processing to filter these out as a safety net.

## Project structure

```
core/                 # Analysis pipeline
  analyze_batched.py  # Claim extraction (batched to avoid rate limits)
  normalize_topics.py # Merge duplicate topic IDs
  verify.py           # Contestation detection
  review.py           # Editorial synthesis
  cost_control.py     # Cost estimation and limits
  ingestion_policy.py # RSS fetch policies by source type

ingest/               # Data ingestion
  rss.py             # RSS feeds + article fetching
  gmail.py           # Gmail API + publisher extraction

deliver/             # Output
  email.py           # HTML email via Gmail API

ui/                  # Streamlit interface (mostly for dev)
  control.py         # Pipeline controls and config
  app.py             # Analytics and log viewer

config/              # Configuration files
  rss_feeds.yaml     # 45+ RSS sources
  briefing_config.json
  delivery_config.json
```

## Logs and observability

Everything is logged to `logs/run.log` in JSONL format. Each event has:
- timestamp
- run_id (traces a briefing through the entire pipeline)
- section (ingest, analyze, verify, review)
- event_type
- payload

There's a Streamlit dashboard (`ui/app.py`) for viewing stats and analyzing runs.

## Limitations and future work

**What could be better:**

- The LLM sometimes creates weird topic IDs that don't merge properly
- Verification only works within the articles I'm reading - it can't catch misinformation that all my sources agree on, though this is unlikely
- The ingestion policy is manually tuned - would be nice to have it adapt automatically
- No support for paywalled content (just uses whatever's in the RSS feed)
- Email delivery is basic HTML - could be much prettier
- Extracting URLs to attach to citations is difficult due to the data sources

**What I'd add with more time:**

- Trend analysis over time (track topics that keep appearing)
- Create archives of the briefings for monthly/quarterly summaries
- Mobile app for reading briefings

## Technical details

**Stack:**
- Python 3.10+
- OpenAI API (gpt-4o-mini)
- Gmail API (OAuth 2.0)
- Trafilatura (article extraction)
- Streamlit (UI)
- JSONL (logging)

**Key libraries:**
```
openai
google-auth
google-auth-oauthlib
google-api-python-client
feedparser
trafilatura
beautifulsoup4
streamlit
python-dotenv
```

## Automation

The pipeline can run automatically via GitHub Actions. Set these secrets:
- `OPENAI_API_KEY`
- `GMAIL_CREDENTIALS` (base64-encoded OAuth JSON)
- `GMAIL_TOKEN` (base64-encoded token JSON)

See `.github/workflows/briefing.yml` for the workflow config.
