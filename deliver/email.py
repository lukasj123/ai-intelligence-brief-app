"""
Email Delivery - Send briefing via email

This module formats and sends the briefing as an HTML email
using SMTP (Gmail or other email service).
"""

import json
import base64
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.observability import log
from core.config import load_config

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
CREDENTIALS_DIR = BASE_DIR / ".credentials"
TOKEN_FILE = CREDENTIALS_DIR / "gmail_token.json"
CREDENTIALS_FILE = CREDENTIALS_DIR / "gmail_credentials.json"

# Gmail API scopes - need send permission
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]


def load_delivery_config():
    """Load delivery configuration from centralized config.yaml."""
    config = load_config()
    email_config = config.get("email", {})

    # Return in the format expected by deliver_briefing
    return {
        "enabled": email_config.get("enabled", False),
        "recipient_email": email_config.get("recipient_email", ""),
        "send_day": email_config.get("send_day", "Monday"),
        "send_time": email_config.get("send_time", "09:00")
    }


def format_briefing_html(briefing_data, config):
    """
    Convert briefing data to HTML email.

    Args:
        briefing_data: Dict with headline, summary, key_points
        config: Pipeline config

    Returns:
        HTML string
    """
    import re

    # Load HTML template
    template_file = TEMPLATE_DIR / "briefing.html"

    if template_file.exists():
        with open(template_file) as f:
            template = f.read()
    else:
        # Fallback inline template
        template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header {
            border-bottom: 3px solid #4A90E2;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }
        .headline {
            font-size: 24px;
            font-weight: bold;
            color: #2C3E50;
            margin: 0 0 10px 0;
        }
        .date {
            color: #7F8C8D;
            font-size: 14px;
        }
        .summary {
            font-size: 16px;
            color: #34495E;
            background-color: #F8F9FA;
            padding: 15px;
            border-left: 4px solid #4A90E2;
            margin: 20px 0;
        }
        .key-points {
            margin: 25px 0;
        }
        .key-points h3 {
            font-size: 18px;
            color: #2C3E50;
            margin-bottom: 15px;
        }
        .key-points ul {
            list-style: none;
            padding: 0;
        }
        .key-points li {
            padding: 12px 0;
            border-bottom: 1px solid #ECF0F1;
        }
        .key-points li:last-child {
            border-bottom: none;
        }
        .key-points li::before {
            content: "▸";
            color: #4A90E2;
            font-weight: bold;
            margin-right: 10px;
        }
        .confidence-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            margin-left: 8px;
        }
        .badge-reported {
            background-color: #E8F4F8;
            color: #2980B9;
        }
        .badge-corroborated {
            background-color: #D5F4E6;
            color: #27AE60;
        }
        .badge-contested {
            background-color: #FADBD8;
            color: #C0392B;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ECF0F1;
            font-size: 12px;
            color: #95A5A6;
            text-align: center;
        }
        .stats {
            display: flex;
            justify-content: space-around;
            margin: 20px 0;
            padding: 15px;
            background-color: #F8F9FA;
            border-radius: 4px;
        }
        .stat {
            text-align: center;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #4A90E2;
        }
        .stat-label {
            font-size: 12px;
            color: #7F8C8D;
            text-transform: uppercase;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="headline">{{HEADLINE}}</div>
            <div class="date">{{DATE}}</div>
        </div>

        <div class="summary">
            {{SUMMARY}}
        </div>

        {{STATS}}

        <div class="key-points">
            <h3>Key Developments</h3>
            <ul>
                {{KEY_POINTS}}
            </ul>
        </div>

        <div class="footer">
            Generated by AI News Briefings · {{SOURCE_COUNT}} sources analyzed
        </div>
    </div>
</body>
</html>
"""

    # Format key points with plain text sources
    key_points_html = "\n".join(
        f"<li>{point}</li>"
        for point in briefing_data.get("key_points", [])
    )

    # Format stats if available
    stats_html = ""
    if config.get("show_stats", True):
        stats_html = """
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{{CLAIM_COUNT}}</div>
                <div class="stat-label">Claims</div>
            </div>
            <div class="stat">
                <div class="stat-value">{{SOURCE_COUNT}}</div>
                <div class="stat-label">Sources</div>
            </div>
        </div>
        """

    # Replace placeholders
    html = template
    html = html.replace("{{HEADLINE}}", briefing_data.get("headline", "AI News Briefing"))
    html = html.replace("{{DATE}}", datetime.now().strftime("%B %d, %Y"))
    html = html.replace("{{SUMMARY}}", briefing_data.get("summary", ""))
    html = html.replace("{{KEY_POINTS}}", key_points_html)
    html = html.replace("{{STATS}}", stats_html)
    html = html.replace("{{CLAIM_COUNT}}", str(config.get("claim_count", 0)))
    html = html.replace("{{SOURCE_COUNT}}", str(config.get("source_count", 0)))

    return html


def get_gmail_service():
    """
    Authenticate and return Gmail API service for sending.
    Uses same credentials as ingestion but with send scope.
    """
    creds = None

    # Load existing token if available
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {CREDENTIALS_FILE}\n"
                    "Please download OAuth credentials from Google Cloud Console."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def send_email(subject, html_body, to_email, run_id=None):
    """
    Send HTML email via Gmail API.

    Args:
        subject: Email subject line
        html_body: HTML content
        to_email: Recipient email address
        run_id: Run identifier for logging

    Uses Gmail API with same credentials as ingestion.
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    log("email", "send_start", {
        "run_id": run_id,
        "to": to_email,
        "subject": subject,
        "method": "gmail_api"
    })

    try:
        service = get_gmail_service()

        # Create message
        message = MIMEMultipart("alternative")
        message["To"] = to_email
        message["Subject"] = subject

        # Add plain text version (fallback)
        # Strip HTML tags for plain text version
        import re as regex_module
        text_body = regex_module.sub('<[^<]+?>', '', html_body)
        text_part = MIMEText(text_body, "plain")
        message.attach(text_part)

        # Attach HTML (should be last for email clients to prefer it)
        html_part = MIMEText(html_body, "html", "utf-8")
        message.attach(html_part)

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        body = {'raw': raw_message}

        # Send via Gmail API
        sent_message = service.users().messages().send(
            userId='me',
            body=body
        ).execute()

        log("email", "send_success", {
            "run_id": run_id,
            "to": to_email,
            "subject": subject,
            "message_id": sent_message['id']
        })

        return True

    except HttpError as error:
        log("email", "send_failed", {
            "run_id": run_id,
            "to": to_email,
            "error": str(error)
        })
        raise
    except Exception as e:
        log("email", "send_failed", {
            "run_id": run_id,
            "to": to_email,
            "error": str(e)
        })
        raise


def deliver_briefing(briefing_data, config=None, run_id=None):
    """
    Main delivery function: format and send briefing email.

    Args:
        briefing_data: Dict with headline, summary, key_points
        config: Optional pipeline config for metadata
        run_id: Run identifier

    Returns:
        True if sent successfully
    """
    if config is None:
        config = {}

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Load delivery config
    delivery_config = load_delivery_config()

    if not delivery_config.get("enabled", False):
        log("email", "delivery_disabled", {"run_id": run_id})
        print("⚠️  Email delivery is disabled in config")
        return False

    recipient = delivery_config.get("recipient_email")
    if not recipient:
        log("email", "no_recipient", {"run_id": run_id})
        print("⚠️  No recipient email configured")
        return False

    # Format HTML
    html = format_briefing_html(briefing_data, config)

    # Create subject line
    subject = f"AI News Briefing: {briefing_data.get('headline', 'Weekly Update')}"

    # Send
    print(f"📧 Sending briefing to {recipient}...")
    send_email(subject, html, recipient, run_id=run_id)
    print(f"✓ Briefing sent successfully!")

    return True


def main():
    """
    Test email delivery with sample briefing.
    """
    # Sample briefing data
    sample_briefing = {
        "headline": "Major AI Developments This Week",
        "summary": "This week saw significant announcements from major AI labs, new regulatory proposals in the EU, and breakthrough research in multimodal learning. Key trends include increased focus on safety frameworks and emerging applications in healthcare.",
        "key_points": [
            "OpenAI announced GPT-5 with enhanced reasoning capabilities",
            "EU proposed new AI safety regulations for frontier models",
            "Stanford researchers published breakthrough in multimodal learning",
            "Healthcare AI applications show promising results in early diagnosis",
            "Industry consolidation continues with major acquisition announcements"
        ]
    }

    sample_config = {
        "claim_count": 24,
        "source_count": 85,
        "show_stats": True
    }

    run_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("📧 Testing email delivery...")
    print("=" * 60)

    try:
        deliver_briefing(sample_briefing, config=sample_config, run_id=run_id)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print("=" * 60)
    print("✓ Test complete!")


if __name__ == "__main__":
    main()
