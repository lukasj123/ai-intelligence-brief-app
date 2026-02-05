"""
Control Panel - Configure and run the AI news briefing pipeline
"""

import streamlit as st
import subprocess
import json
import os
from pathlib import Path
import time
import sys

# Add parent directory to path to import core modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config, save_config

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

st.set_page_config(layout="wide", page_title="AI News Briefings — Control Panel")

# Load config from centralized config.yaml
config = load_config()

# Title
st.title("AI News Briefings — Control Panel")
st.caption("Configure prompts, run the pipeline, and view results")

# Layout: Tabs for different sections
tab1, tab2, tab3 = st.tabs(["Configuration", "Pipeline Control", "Results"])

#TAB 1: Configuration
with tab1:
    st.header("Configuration")

    st.subheader("Analyzer Instructions")
    st.caption("Customize how claims are extracted from articles")
    analyzer_instructions = st.text_area(
        "Focus areas and priorities:",
        value=config["analyzer_instructions"],
        height=100,
        help="Guide the LLM on what types of claims to prioritize"
    )

    st.subheader("Reviewer Focus")
    st.caption("Customize what gets included in the final briefing")
    reviewer_focus = st.text_area(
        "Relevance criteria and exclusions:",
        value=config["reviewer_focus"],
        height=100,
        help="Guide the LLM on what to include/exclude in the briefing"
    )

    st.subheader("Pipeline Parameters")
    col1, col2, col3 = st.columns(3)
    with col1:
        lookback_days = st.number_input(
            "Lookback Days",
            min_value=1,
            max_value=30,
            value=config["lookback_days"],
            help="Only include articles from the last N days"
        )
    with col2:
        max_key_points = st.number_input(
            "Max Key Points",
            min_value=3,
            max_value=25,
            value=config.get("max_key_points", 10),
            help="Maximum number of key points in the final briefing"
        )
    with col3:
        skip_normalization = st.checkbox(
            "Skip Normalization",
            value=config["skip_normalization"],
            help="Use all discovered articles without time/quality filtering"
        )

    st.subheader("Email Delivery")
    st.caption("Configure automated email briefings")

    email_config = config.get("email", {})
    enable_email = st.checkbox(
        "Enable Email Delivery",
        value=email_config.get("enabled", False),
        help="Send briefing via email after pipeline completes"
    )

    recipient_email = st.text_input(
        "Recipient Email",
        value=email_config.get("recipient_email", ""),
        help="Where to send the briefing"
    )

    if st.button("Save Configuration", type="primary"):
        config["analyzer_instructions"] = analyzer_instructions
        config["reviewer_focus"] = reviewer_focus
        config["lookback_days"] = lookback_days
        config["max_key_points"] = max_key_points
        config["skip_normalization"] = skip_normalization
        if "email" not in config:
            config["email"] = {}
        config["email"]["enabled"] = enable_email
        config["email"]["recipient_email"] = recipient_email
        save_config(config)
        st.success("Configuration saved!")

#TAB 2: Pipeline Control
with tab2:
    st.header("Pipeline Control")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Step 1a: RSS Ingestion")
        st.caption("Discover and fetch articles from RSS feeds")

        if st.button("Run RSS Ingestion", type="primary", use_container_width=True):
            with st.spinner("Running ingestion... (this may take 2-3 minutes)"):
                try:
                    result = subprocess.run(
                        ["python", "-m", "ingest.rss"],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=300
                    )

                    if result.returncode == 0:
                        st.success("Ingestion complete!")

                        # Parse logs to show stats
                        log_file = LOGS_DIR / "run.log"
                        if log_file.exists():
                            with open(log_file) as f:
                                lines = f.readlines()
                                # Get last run summary
                                for line in reversed(lines[-50:]):
                                    if '"event_type": "rss.run_summary"' in line:
                                        data = json.loads(line)
                                        payload = data["payload"]
                                        st.metric("Total Articles", payload["total_items"])
                                        break

                                # Get fetch summary
                                for line in reversed(lines[-50:]):
                                    if '"event_type": "rss.fetch_summary"' in line:
                                        data = json.loads(line)
                                        payload = data["payload"]
                                        col_a, col_b = st.columns(2)
                                        col_a.metric("Fetched", payload["fetch_success"])
                                        col_b.metric("Success Rate", f"{payload['fetch_success_rate']}%")
                                        break
                    else:
                        st.error(f"Ingestion failed: {result.stderr}")

                except subprocess.TimeoutExpired:
                    st.error("Ingestion timed out (5 min limit)")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    with col2:
        st.subheader("Step 1b: Gmail Ingestion")
        st.caption("Fetch newsletters from Gmail")

        if st.button("Run Gmail Ingestion", type="primary", use_container_width=True):
            with st.spinner("Fetching emails from Gmail... (this may take 1-2 minutes)"):
                try:
                    result = subprocess.run(
                        ["python", "-m", "ingest.gmail"],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=180
                    )

                    if result.returncode == 0:
                        st.success("Gmail ingestion complete!")

                        # Parse output for stats
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if "Fetched" in line and "items" in line:
                                st.info(line)
                    else:
                        st.error(f"Gmail ingestion failed: {result.stderr}")

                except subprocess.TimeoutExpired:
                    st.error("Gmail ingestion timed out (3 min limit)")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    with col3:
        st.subheader("Step 2: Full Pipeline")
        st.caption("Analyze, verify, and generate briefing")

        if st.button("Run Full Pipeline", type="primary", use_container_width=True):
            # Check if data exists
            if not (DATA_DIR / "raw_sources.json").exists():
                st.error("No data found! Run ingestion first.")
            else:
                with st.spinner("Running analysis pipeline... (this may take 3-5 minutes)"):
                    try:
                        # Set environment variables for config
                        env = os.environ.copy()
                        env["ANALYZER_INSTRUCTIONS"] = config["analyzer_instructions"]
                        env["REVIEWER_FOCUS"] = config["reviewer_focus"]
                        env["LOOKBACK_DAYS"] = str(config["lookback_days"])
                        env["MAX_KEY_POINTS"] = str(config.get("max_key_points", 10))
                        if config["skip_normalization"]:
                            env["SKIP_NORMALIZATION"] = "1"

                        result = subprocess.run(
                            ["python", "run.py"],
                            cwd=str(BASE_DIR),
                            capture_output=True,
                            text=True,
                            timeout=600,
                            env=env
                        )

                        if result.returncode == 0:
                            st.success("Pipeline complete!")

                            # Store output for results tab
                            st.session_state["last_output"] = result.stdout
                            st.session_state["last_run_time"] = time.time()

                            # Show quick preview
                            st.text_area("Output Preview", result.stdout, height=300)
                            st.info("See full results in the 'Results' tab")
                        else:
                            st.error(f"Pipeline failed: {result.stderr}")
                            st.text_area("Error Details", result.stderr, height=200)

                    except subprocess.TimeoutExpired:
                        st.error("Pipeline timed out (10 min limit)")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

    st.divider()
    st.subheader("Complete Automated Pipeline")
    st.caption("Run Gmail + RSS ingestion → Analysis → Email delivery (all-in-one)")

    if st.button("Run Complete Pipeline with Email", type="secondary", use_container_width=True):
        if not config.get("enable_email") or not config.get("recipient_email"):
            st.warning("Email delivery not configured. Configure in the Configuration tab first.")
        else:
            with st.spinner("Running complete pipeline... (this may take 5-10 minutes)"):
                try:
                    # Set environment variables
                    env = os.environ.copy()
                    env["ANALYZER_INSTRUCTIONS"] = config["analyzer_instructions"]
                    env["REVIEWER_FOCUS"] = config["reviewer_focus"]
                    env["LOOKBACK_DAYS"] = str(config["lookback_days"])
                    env["MAX_KEY_POINTS"] = str(config.get("max_key_points", 10))
                    if config["skip_normalization"]:
                        env["SKIP_NORMALIZATION"] = "1"

                    # Create delivery config for email
                    delivery_config = {
                        "enabled": True,
                        "recipient_email": config["recipient_email"]
                    }
                    delivery_config_path = BASE_DIR / "config" / "delivery_config.json"
                    with open(delivery_config_path, 'w') as f:
                        json.dump(delivery_config, f, indent=2)

                    result = subprocess.run(
                        ["python", "briefing_pipeline.py"],
                        cwd=str(BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=900,
                        env=env
                    )

                    if result.returncode == 0:
                        st.success("Complete pipeline finished!")
                        st.balloons()

                        # Store output
                        st.session_state["last_output"] = result.stdout
                        st.session_state["last_run_time"] = time.time()

                        # Show preview
                        st.text_area("Output Preview", result.stdout, height=400)
                        st.info("Check your email inbox and see the 'Results' tab")
                    else:
                        st.error(f"Pipeline failed: {result.stderr}")
                        st.text_area("Error Details", result.stderr, height=200)

                except subprocess.TimeoutExpired:
                    st.error("Pipeline timed out (15 min limit)")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

#TAB 3: Results
with tab3:
    st.header("Pipeline Results")

    if "last_output" in st.session_state:
        run_time = st.session_state.get("last_run_time", 0)
        st.caption(f"Last run: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(run_time))}")

        # Parse the output to extract stats
        output = st.session_state["last_output"]

        # Extract stats from the output
        lines = output.split('\n')

        stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)

        for line in lines:
            if "Normalizing" in line and "discovered items" in line:
                # Extract: "📊 Normalizing 223 discovered items..."
                parts = line.split()
                if len(parts) >= 3:
                    stats_col1.metric("Discovered", parts[2])

            if "Kept" in line and "after normalization" in line:
                # Extract: "✓ Kept 80 items after normalization"
                parts = line.split()
                if len(parts) >= 3:
                    stats_col2.metric("After Filter", parts[2])

            if "Analyzing" in line and "articles" in line:
                # Extract: "🔍 Analyzing 80 articles..."
                parts = line.split()
                if len(parts) >= 3:
                    stats_col3.metric("Analyzed", parts[2])

            if "Normalizing" in line and "claim topics" in line:
                # Extract: "🔗 Normalizing 16 claim topics..."
                parts = line.split()
                if len(parts) >= 3:
                    stats_col4.metric("Claims", parts[2])

        st.divider()

        # Display full briefing
        st.subheader("Final Briefing")

        # Extract content between the ====== lines
        in_briefing = False
        briefing_lines = []

        for line in lines:
            if "=" * 50 in line:
                if not in_briefing:
                    in_briefing = True
                    continue
                else:
                    break
            if in_briefing:
                briefing_lines.append(line)

        if briefing_lines:
            briefing_text = '\n'.join(briefing_lines).strip()
            st.markdown(briefing_text)

            # Download button
            st.download_button(
                label="Download Briefing",
                data=briefing_text,
                file_name=f"briefing_{time.strftime('%Y%m%d_%H%M%S', time.localtime(run_time))}.txt",
                mime="text/plain"
            )
        else:
            st.info("No briefing found in output. Try running the pipeline again.")

        st.divider()

        # Show full output in an expander
        with st.expander("View Full Output"):
            st.text(output)
    else:
        st.info("No results yet. Run the pipeline from the 'Pipeline Control' tab.")

# Sidebar: Status info
with st.sidebar:
    st.header("Status")

    # Check if data exists
    raw_data_exists = (DATA_DIR / "raw_sources.json").exists()

    if raw_data_exists:
        with open(DATA_DIR / "raw_sources.json") as f:
            data = json.load(f)
            st.metric("Articles Available", len(data))
        st.success("Data ready")
    else:
        st.warning("No data - run ingestion first")

    # Check logs
    log_file = LOGS_DIR / "run.log"
    if log_file.exists():
        log_size = log_file.stat().st_size / 1024  # KB
        st.metric("Log Size", f"{log_size:.1f} KB")

    st.divider()

    st.caption("**Quick Start:**")
    st.caption("1. Configure prompts (optional)")
    st.caption("2. Run Ingestion")
    st.caption("3. Run Full Pipeline")
    st.caption("4. View Results")
