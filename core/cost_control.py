import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
COST_LOG_FILE = BASE_DIR / "logs" / "costs.jsonl"

PRICING = {
    "gpt-4o-mini": {
        "input": 0.150 / 1_000_000,
        "output": 0.600 / 1_000_000
    }
}

MAX_ARTICLES_PER_RUN = 200
MAX_ARTICLE_LENGTH = 10_000
WARNING_THRESHOLD_USD = 0.50
EMAIL_ALERT_THRESHOLD_USD = 1.00

def estimate_tokens(text):
    return len(text) // 4


def estimate_cost(input_tokens, output_tokens, model="gpt-4o-mini"):
    pricing = PRICING.get(model, PRICING["gpt-4o-mini"])
    input_cost = input_tokens * pricing["input"]
    output_cost = output_tokens * pricing["output"]
    return input_cost + output_cost


def check_limits(raw_data, run_id="unknown"):
    article_count = len(raw_data)
    warnings = []

    if article_count > MAX_ARTICLES_PER_RUN:
        warnings.append(
            f"⚠️  LIMIT EXCEEDED: {article_count} articles (max: {MAX_ARTICLES_PER_RUN})"
        )
        warnings.append(f"   Only the first {MAX_ARTICLES_PER_RUN} will be processed")

    total_chars = sum(len(item.get('content', '')) for item in raw_data[:MAX_ARTICLES_PER_RUN])
    total_tokens = total_chars // 4
    estimated_output = int(total_tokens * 0.15)
    estimated_cost = estimate_cost(total_tokens, estimated_output)

    if estimated_cost > WARNING_THRESHOLD_USD:
        warnings.append(
            f"⚠️  HIGH COST WARNING: Estimated ${estimated_cost:.2f} for this run"
        )
        warnings.append(f"   ({total_tokens:,} input tokens + {estimated_output:,} output tokens)")

    long_articles = [
        item['id'] for item in raw_data
        if len(item.get('content', '')) > MAX_ARTICLE_LENGTH
    ]

    if long_articles:
        warnings.append(
            f"⚠️  {len(long_articles)} articles exceed {MAX_ARTICLE_LENGTH:,} chars (will be truncated)"
        )

    result = {
        "within_limits": article_count <= MAX_ARTICLES_PER_RUN,
        "article_count": article_count,
        "articles_to_process": min(article_count, MAX_ARTICLES_PER_RUN),
        "estimated_input_tokens": total_tokens,
        "estimated_output_tokens": estimated_output,
        "estimated_cost_usd": estimated_cost,
        "warnings": warnings,
        "run_id": run_id
    }

    return result


def log_cost(run_id, actual_tokens_used, actual_cost):
    """
    Log actual cost after a run.

    Args:
        run_id: Run identifier
        actual_tokens_used: dict with 'input' and 'output' keys
        actual_cost: Actual USD cost
    """
    COST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "tokens": actual_tokens_used,
        "cost_usd": actual_cost,
        "model": "gpt-4o-mini"
    }

    with open(COST_LOG_FILE, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')


def get_monthly_costs():
    if not COST_LOG_FILE.exists():
        return {"month": datetime.now().strftime("%Y-%m"), "total_usd": 0.0, "run_count": 0}

    current_month = datetime.now().strftime("%Y-%m")
    total_cost = 0.0
    run_count = 0

    with open(COST_LOG_FILE) as f:
        for line in f:
            entry = json.loads(line)
            if entry['timestamp'].startswith(current_month):
                total_cost += entry['cost_usd']
                run_count += 1

    return {
        "month": current_month,
        "total_usd": total_cost,
        "run_count": run_count
    }


def send_cost_alert(estimated_cost, check_result):
    if estimated_cost < EMAIL_ALERT_THRESHOLD_USD:
        return

    try:
        from deliver.email import send_email
        from core.config import load_briefing_config

        config = load_briefing_config()
        recipient = config.get('recipient_email')

        if not recipient:
            print("⚠️  Cannot send cost alert: no recipient email configured")
            return

        subject = f"⚠️  HIGH COST ALERT: ${estimated_cost:.2f} briefing run"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #dc3545;">⚠️ High Cost Alert</h2>

            <p>Your AI briefing pipeline is about to run with an estimated cost of <strong>${estimated_cost:.2f}</strong>.</p>

            <h3>Details:</h3>
            <ul>
                <li><strong>Articles:</strong> {check_result['articles_to_process']:,}</li>
                <li><strong>Estimated tokens:</strong> {check_result['estimated_input_tokens']:,} input + {check_result['estimated_output_tokens']:,} output</li>
                <li><strong>Estimated cost:</strong> ${estimated_cost:.4f}</li>
            </ul>

            <h3>Why so high?</h3>
            <p>This could be due to:</p>
            <ul>
                <li>Email spam flooding your inbox</li>
                <li>Too many RSS sources</li>
                <li>Very long articles</li>
            </ul>

            <h3>What to do:</h3>
            <ol>
                <li>Check your Gmail for spam emails</li>
                <li>Review RSS feeds in <code>config/rss_feeds.yaml</code></li>
                <li>Consider reducing lookback period</li>
                <li>Check <code>logs/costs.jsonl</code> for patterns</li>
            </ol>

            <p style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
                Automated alert from AI News Briefings cost control system
            </p>
        </body>
        </html>
        """

        print(f"📧 Sending cost alert to {recipient}...")
        send_email(subject, html_body, recipient, run_id=check_result['run_id'])
        print(f"✓ Cost alert sent!")

    except Exception as e:
        print(f"⚠️  Failed to send cost alert: {e}")


def print_cost_summary(check_result):
    """
    Print a cost summary before processing.
    """
    print("\n" + "=" * 60)
    print("💰 COST CONTROL CHECK")
    print("=" * 60)

    print(f"Articles to process: {check_result['articles_to_process']}/{check_result['article_count']}")
    print(f"Estimated tokens: {check_result['estimated_input_tokens']:,} input + {check_result['estimated_output_tokens']:,} output")
    print(f"Estimated cost: ${check_result['estimated_cost_usd']:.4f}")

    monthly = get_monthly_costs()
    print(f"\nMonth-to-date ({monthly['month']}): ${monthly['total_usd']:.2f} ({monthly['run_count']} runs)")

    if check_result['warnings']:
        print("\n" + "\n".join(check_result['warnings']))

    if check_result['estimated_cost_usd'] >= EMAIL_ALERT_THRESHOLD_USD:
        send_cost_alert(check_result['estimated_cost_usd'], check_result)

    print("=" * 60 + "\n")


def enforce_limits(raw_data):
    limited_data = raw_data[:MAX_ARTICLES_PER_RUN]

    for item in limited_data:
        if len(item.get('content', '')) > MAX_ARTICLE_LENGTH:
            item['content'] = item['content'][:MAX_ARTICLE_LENGTH] + "\n\n[Article truncated for cost control]"

    return limited_data
