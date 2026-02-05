import json
from pathlib import Path
import pandas as pd
import streamlit as st

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "logs" / "run.log"
DATA_PATH = BASE_DIR / "data" / "raw_sources.json"

st.set_page_config(layout="wide", page_title="AI News Briefings — Inspector")

st.title("AI News Briefings — System Inspector")

# Load logs
def load_logs():
    records = []
    if not LOG_PATH.exists():
        return pd.DataFrame()

    with open(LOG_PATH) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(records)

logs_df = load_logs()

if logs_df.empty:
    st.warning("No logs found.")
    st.stop()

# Run selector
run_ids = sorted(logs_df["run_id"].unique())
selected_run = st.selectbox("Select run_id", run_ids)

run_logs = logs_df[logs_df["run_id"] == selected_run]

# Ingestion overview
st.header("📥 Ingestion Overview")

summary = run_logs[run_logs["event_type"] == "rss.run_summary"]["payload"].iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Feeds", summary["total_feeds"])
col2.metric("Unique Articles", summary["total_items"])
col3.metric("Items Skipped", summary["total_skipped"])

# Show dedup metrics if available
if "duplicates_merged" in summary:
    col4.metric("Duplicates Merged", summary["duplicates_merged"])
else:
    col4.metric("Duplicates Merged", "N/A")

# Deduplication metrics
dedup_logs = run_logs[run_logs["event_type"] == "rss.dedup_summary"]
if not dedup_logs.empty:
    st.header("🔗 Deduplication Metrics")

    dedup = dedup_logs["payload"].iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Items Processed", dedup["items_processed"])
    col2.metric("Unique URLs", dedup["unique_urls"])
    col3.metric("Duplicates Merged", dedup["duplicates_merged"])
    col4.metric("Dedup Rate", f"{dedup['dedup_rate']}%")

    st.info(f"📊 {dedup['multi_source_articles']} articles found in multiple RSS feeds (multi-source verification candidates)")

# Multi-source articles
multi_source_logs = run_logs[run_logs["event_type"] == "rss.multi_source_article"]
if not multi_source_logs.empty:
    st.header("🌐 Multi-Source Articles")
    st.caption("Articles reported by multiple publishers (stronger corroboration)")

    multi_source_rows = []
    for _, row in multi_source_logs.iterrows():
        payload = row["payload"]
        multi_source_rows.append({
            "title": payload["title"],
            "url": payload["url"],
            "publishers": ", ".join(payload["publishers"]),
            "source_types": ", ".join(payload["source_types"]),
            "source_count": payload["source_count"]
        })

    multi_df = pd.DataFrame(multi_source_rows)
    st.dataframe(multi_df.sort_values("source_count", ascending=False), use_container_width=True)

# Feed diagnostics
st.header("🧪 Feed Diagnostics")

feed_rows = []
for _, row in run_logs[run_logs["event_type"] == "rss.feed_summary"].iterrows():
    payload = row["payload"]
    feed_rows.append({
    "publisher": payload.get("publisher", "unknown"),
    "source_type": payload.get("source_type", "unknown"),
    "items_ingested": payload.get("items_ingested", 0),
    "items_skipped": payload.get("items_skipped", 0),
    "avg_content_length": payload.get("avg_content_length", 0),
    "no_content": payload.get("skip_breakdown", {}).get("no_content", 0),
    "too_short": payload.get("skip_breakdown", {}).get("too_short", 0),
    })


feed_df = pd.DataFrame(feed_rows)

st.dataframe(feed_df.sort_values("items_ingested", ascending=False), use_container_width=True)

# Charts
st.subheader("📊 Items by Source Type")
st.bar_chart(feed_df.groupby("source_type")["items_ingested"].sum())

st.subheader("📊 Skipped Reasons")
skip_totals = {
    "no_content": feed_df["no_content"].sum(),
    "too_short": feed_df["too_short"].sum(),
}
st.bar_chart(pd.DataFrame.from_dict(skip_totals, orient="index", columns=["count"]))

# Raw article browser
st.header("📄 Raw Articles")

if not DATA_PATH.exists():
    st.warning("raw_sources.json not found.")
    st.stop()

with open(DATA_PATH) as f:
    articles = json.load(f)

# Handle both old (single publisher) and new (multi-publisher) formats
for article in articles:
    # Convert old format to new format for compatibility
    if "publisher" in article and "publishers" not in article:
        article["publishers"] = [article["publisher"]]
    if "source_type" in article and "source_types" not in article:
        article["source_types"] = [article["source_type"]]

    # Add convenience fields for filtering
    article["publishers_str"] = ", ".join(article.get("publishers", []))
    article["source_types_str"] = ", ".join(article.get("source_types", []))

articles_df = pd.DataFrame(articles)

# Extract unique values for filters (flatten lists)
all_source_types = set()
all_publishers = set()

for article in articles:
    all_source_types.update(article.get("source_types", []))
    all_publishers.update(article.get("publishers", []))

source_types = sorted(all_source_types)
publishers = sorted(all_publishers)

col1, col2, col3 = st.columns(3)
selected_types = col1.multiselect("Filter by source_type", source_types, default=source_types)
selected_publishers = col2.multiselect("Filter by publisher", publishers, default=publishers)

# Filter for multi-source only
show_multi_source_only = col3.checkbox("Multi-source only", value=False)

# Filter articles
filtered = articles_df[
    articles_df["source_types"].apply(lambda x: any(t in selected_types for t in x))
    & articles_df["publishers"].apply(lambda x: any(p in selected_publishers for p in x))
]

if show_multi_source_only:
    filtered = filtered[filtered["publishers"].apply(len) > 1]

st.write(f"Showing {len(filtered)} articles (displaying first 50)")

for _, row in filtered.head(50).iterrows():
    # Create header with multi-source indicator
    publishers_display = row["publishers_str"]
    multi_source_badge = "🌐 " if len(row["publishers"]) > 1 else ""

    with st.expander(f"{multi_source_badge}{publishers_display} — {row['title']}"):
        st.markdown(f"**URL:** {row['url']}")
        st.markdown(f"**Publishers:** {row['publishers_str']}")
        st.markdown(f"**Source Types:** {row['source_types_str']}")
        st.markdown(f"**Ingestion Tier:** {row.get('ingestion_tier', 'N/A')}")
        st.markdown(f"**Fetch Full Article:** {row.get('fetch_full_article', 'N/A')}")
        st.markdown(f"**Published:** {row.get('published', 'N/A')}")
        st.markdown(f"**Discovered At:** {row.get('discovered_at', 'N/A')}")
        st.markdown("---")
        st.write(row["content"][:2000] + "..." if len(row["content"]) > 2000 else row["content"])
