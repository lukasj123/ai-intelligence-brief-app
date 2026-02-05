"""
Gmail Ingestion - Fetch newsletters and emails from Gmail

This module authenticates with Gmail API and fetches emails
containing AI news and newsletters for the briefing pipeline.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
from bs4 import BeautifulSoup
from openai import OpenAI

from core.observability import log
from core.config import get_lookback_days

# Gmail API scopes - read-only for ingestion, send for email delivery
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BASE_DIR / ".credentials"
TOKEN_FILE = CREDENTIALS_DIR / "gmail_token.json"
CREDENTIALS_FILE = CREDENTIALS_DIR / "gmail_credentials.json"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / ".cache"
PUBLISHER_CACHE_FILE = CACHE_DIR / "publisher_cache.json"

# OpenAI client (lazy initialization)
_openai_client = None


def get_openai_client():
    """Get or create OpenAI client (lazy initialization)."""
    global _openai_client
    if _openai_client is None:
        # Try to load .env file if it exists
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment. "
                "Please set it in .env file or environment variables."
            )
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def get_gmail_service():
    """
    Authenticate and return Gmail API service.

    First-time setup:
    1. Download OAuth credentials from Google Cloud Console
    2. Save as .credentials/gmail_credentials.json
    3. Run this - it will open browser for authorization
    4. Token saved to .credentials/gmail_token.json for future use
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
                    "Please download OAuth credentials from Google Cloud Console:\n"
                    "1. Go to https://console.cloud.google.com/apis/credentials\n"
                    "2. Create OAuth 2.0 Client ID (Desktop app)\n"
                    "3. Download JSON and save as .credentials/gmail_credentials.json"
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


def extract_email_content(message_data):
    """
    Extract text content from email message.
    Handles both plain text and HTML emails.
    """
    payload = message_data.get('payload', {})
    parts = payload.get('parts', [])

    # Try to get plain text first
    body_text = ""

    if parts:
        for part in parts:
            mime_type = part.get('mimeType', '')

            if mime_type == 'text/plain':
                body_data = part.get('body', {}).get('data', '')
                if body_data:
                    body_text = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                    break
            elif mime_type == 'text/html':
                body_data = part.get('body', {}).get('data', '')
                if body_data:
                    html_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                    # Parse HTML to text
                    soup = BeautifulSoup(html_content, 'html.parser')
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    body_text = soup.get_text(separator='\n', strip=True)
    else:
        # Simple message without parts
        body_data = payload.get('body', {}).get('data', '')
        if body_data:
            body_text = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')

    return body_text.strip()


def get_header(headers, name):
    """Extract header value by name."""
    for header in headers:
        if header['name'].lower() == name.lower():
            return header['value']
    return None


# Publisher Cache System

def load_publisher_cache():
    """Load publisher cache from disk."""
    if not PUBLISHER_CACHE_FILE.exists():
        return {}

    try:
        with open(PUBLISHER_CACHE_FILE) as f:
            return json.load(f)
    except Exception as e:
        log("gmail", "cache_load_error", {"error": str(e)})
        return {}


def save_publisher_cache(cache):
    """Save publisher cache to disk."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(PUBLISHER_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log("gmail", "cache_save_error", {"error": str(e)})


def lookup_publisher_cache(email_address):
    """
    Look up cached publisher name by email address.

    Args:
        email_address: Email address to look up

    Returns:
        Cached publisher name if found, None otherwise
    """
    cache = load_publisher_cache()
    return cache.get(email_address)


def cache_publisher(email_address, publisher_name):
    """
    Cache a verified publisher name for an email address.

    Args:
        email_address: Email address
        publisher_name: Verified publisher name
    """
    cache = load_publisher_cache()
    cache[email_address] = publisher_name
    save_publisher_cache(cache)



def extract_email_from_header(from_header):
    """
    Extract email address from From header.

    Examples:
        "AI Weekly <newsletter@aiweekly.com>" → "newsletter@aiweekly.com"
        "newsletter@example.com" → "newsletter@example.com"
    """
    import re

    if not from_header:
        return None

    # Try angle bracket format first
    match = re.search(r'<(.+?)>', from_header)
    if match:
        return match.group(1).strip()

    # Try plain email pattern
    match = re.search(r'[\w\.-]+@[\w\.-]+', from_header)
    if match:
        return match.group(0).strip()

    return None


def try_regex_extraction(from_header, subject=None, list_id=None):
    """
    Try deterministic regex-based publisher name extraction.

    Args:
        from_header: Email From header
        subject: Email subject (optional, for additional context)
        list_id: Email List-Id header (optional, good source for newsletter names)

    Returns:
        Best guess publisher name from regex extraction
    """
    import re

    if not from_header:
        return "Unknown Publisher"

    # Strategy 1: Extract display name from "Display Name <email@domain.com>" format
    match = re.match(r'^(.+?)\s*<(.+?)>$', from_header)
    if match:
        display_name = match.group(1).strip().strip('"').strip("'")
        if display_name and not display_name.lower() in ['via', 'no-reply', 'noreply']:
            return display_name

    # Strategy 2: Try List-Id header (often has newsletter name)
    if list_id:
        # Example: "<importai.jack-clark.net>" → "Import AI"
        # Example: "AI Weekly Newsletter <list.aiweekly.com>" → "AI Weekly Newsletter"
        match = re.match(r'^(.+?)\s*<', list_id)
        if match:
            list_name = match.group(1).strip().strip('"')
            if list_name:
                return list_name

    # Strategy 3: Parse email address intelligently
    email = extract_email_from_header(from_header)
    if email:
        # Get local part (before @)
        local_part = email.split('@')[0]

        # Skip generic addresses
        if local_part.lower() in ['noreply', 'no-reply', 'newsletter', 'info', 'hello']:
            # Try domain instead
            domain = email.split('@')[1].split('.')[0]
            return domain.replace('-', ' ').replace('_', ' ').title()

        # Convert to readable name
        # "newsletter.subscriptions" → "Newsletter Subscriptions"
        readable_name = local_part.replace('.', ' ').replace('_', ' ').replace('-', ' ')
        readable_name = ' '.join(word.capitalize() for word in readable_name.split())

        return readable_name if readable_name else "Unknown Newsletter"

    # Fallback: use header as-is
    return from_header


def verify_publisher_with_llm(regex_guess, from_header, subject, body_preview=""):
    """
    Use LLM to verify and potentially improve regex-extracted publisher name.

    This is the "semantic check" - determining if something "looks reasonable"
    is inherently a semantic task that LLMs are good at.

    Args:
        regex_guess: Publisher name extracted by regex
        from_header: Raw From header
        subject: Email subject
        body_preview: First ~500 chars of email body (optional)

    Returns:
        Verified/corrected publisher name
    """
    system_prompt = (
        "You are a publisher name verification assistant.\n"
        "Your job is to verify or correct publisher names extracted from email headers.\n"
        "Return ONLY the verified publisher name, nothing else."
    )

    # Build prompt with optional body preview
    body_section = ""
    if body_preview:
        body_section = f"\nEmail body preview:\n{body_preview}\n"

    user_prompt = f"""
Email headers:
From: {from_header}
Subject: {subject}
{body_section}
Regex extracted publisher name: "{regex_guess}"

Task: Verify if this publisher name looks correct and professional.
- If it looks good, return it as-is
- If it needs minor fixes (capitalization, formatting), fix it
- If it's clearly wrong or generic (like "Newsletter" or "No Reply"), try to infer the actual publisher from the email headers and content
- Pay special attention to company/product names mentioned in the subject and body preview
- Return ONLY the publisher name, no explanation

Publisher name:"""

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=50,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        verified_name = response.choices[0].message.content.strip()

        verified_name = verified_name.strip('"').strip("'").strip()

        if not verified_name or len(verified_name) > 100:
            return regex_guess

        return verified_name

    except Exception as e:
        log("gmail", "llm_verification_error", {
            "error": str(e),
            "regex_guess": regex_guess
        })
        return regex_guess


def extract_publisher_name(from_header, subject=None, list_id=None, body_preview=None, force_reverify=False):
    """
    Extract publisher name with LLM-verified caching.

    Flow:
    1. Check cache (email → publisher mapping) - if found, return cached value
    2. If not cached, try regex extraction
    3. Verify regex result with cheap LLM (gpt-4o-mini)
    4. Cache the verified result for future use

    Cost: ~$0.00003 per email on first extraction, then FREE forever via cache

    Args:
        from_header: Email From header (required)
        subject: Email subject (optional, improves LLM verification)
        list_id: Email List-Id header (optional, improves regex extraction)
        body_preview: First ~500 chars of email body (optional, improves LLM verification)
        force_reverify: Skip cache and re-verify (for debugging)

    Returns:
        Verified publisher name
    """
    # Extract email address for cache lookup
    email = extract_email_from_header(from_header)

    if not email:
        # Can't cache without email address, fall back to regex
        return try_regex_extraction(from_header, subject, list_id)

    # Check cache first - if found, trust it completely
    if not force_reverify:
        cached = lookup_publisher_cache(email)
        if cached:
            return cached  # ✓ Free, fast, already LLM-verified

    # Not cached - run regex extraction + LLM verification
    regex_guess = try_regex_extraction(from_header, subject, list_id)

    # LLM verification (semantic check)
    verified_name = verify_publisher_with_llm(
        regex_guess=regex_guess,
        from_header=from_header,
        subject=subject or "(No Subject)",
        body_preview=body_preview
    )

    # Cache the verified result
    cache_publisher(email, verified_name)

    log("gmail", "publisher_verified", {
        "email": email,
        "regex_guess": regex_guess,
        "verified_name": verified_name,
        "cached": True
    })

    return verified_name


def extract_publisher_name_legacy(from_header):
    """
    Legacy regex-only publisher name extraction (no LLM verification).
    Kept for reference. Use extract_publisher_name() instead.

    Examples:
        "AI Weekly <newsletter@aiweekly.com>" → "AI Weekly"
        "newsletter.subscriptions.email@gmail.com" → "Newsletter Subscriptions Email"
        "ImportAI <jack@jack-clark.net>" → "ImportAI"
    """
    import re

    if not from_header:
        return "Unknown Publisher"

    # Try to extract display name from "Display Name <email@domain.com>" format
    match = re.match(r'^(.+?)\s*<(.+?)>$', from_header)
    if match:
        display_name = match.group(1).strip()
        # Remove quotes if present
        display_name = display_name.strip('"').strip("'")
        if display_name:
            return display_name

    # No display name found, try to parse the email address
    # Extract email if it's the only thing in the header
    email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_header)
    if email_match:
        email = email_match.group(0)
        # Get the local part (before @)
        local_part = email.split('@')[0]

        # Convert to title case and replace separators with spaces
        # "newsletter.subscriptions.email" → "Newsletter Subscriptions Email"
        readable_name = local_part.replace('.', ' ').replace('_', ' ').replace('-', ' ')
        readable_name = ' '.join(word.capitalize() for word in readable_name.split())

        return readable_name if readable_name else "Unknown Newsletter"

    # Fallback: use the header as-is
    return from_header


def fetch_emails(lookback_days=7, max_results=100, run_id=None):
    """
    Fetch recent emails from Gmail.

    Args:
        lookback_days: Only fetch emails from last N days
        max_results: Maximum number of emails to fetch
        run_id: Run identifier for logging

    Returns:
        List of email items in raw_sources format
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    log("gmail", "start", {
        "run_id": run_id,
        "lookback_days": lookback_days,
        "max_results": max_results
    })

    try:
        service = get_gmail_service()

        # Build query: emails from last N days
        cutoff_date = datetime.now() - timedelta(days=lookback_days)
        query = f'after:{cutoff_date.strftime("%Y/%m/%d")}'

        # Search for messages
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get('messages', [])

        log("gmail", "search_complete", {
            "run_id": run_id,
            "messages_found": len(messages),
            "query": query
        })

        if not messages:
            log("gmail", "no_messages", {"run_id": run_id})
            return []

        # Fetch full message details
        items = []
        skipped = {
            "no_content": 0,
            "too_short": 0,
            "parse_error": 0
        }

        for idx, msg in enumerate(messages):
            try:
                # Get full message
                message = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()

                headers = message['payload']['headers']
                subject = get_header(headers, 'Subject') or "(No Subject)"
                sender = get_header(headers, 'From') or "(Unknown Sender)"
                list_id = get_header(headers, 'List-Id')
                date_str = get_header(headers, 'Date')

                # Skip self-sent briefing emails to avoid recursive ingestion
                if subject.startswith("AI News Briefing:"):
                    skipped["parse_error"] += 1
                    log("gmail", "skip_self_briefing", {
                        "run_id": run_id,
                        "subject": subject,
                        "reason": "Self-generated briefing email"
                    })
                    continue

                # Parse date
                try:
                    received_date = parsedate_to_datetime(date_str)
                except:
                    received_date = datetime.now()

                # Extract content
                content = extract_email_content(message)

                if not content:
                    skipped["no_content"] += 1
                    log("gmail", "skip_no_content", {
                        "run_id": run_id,
                        "subject": subject,
                        "sender": sender
                    })
                    continue

                # Basic quality filter
                if len(content) < 100:
                    skipped["too_short"] += 1
                    log("gmail", "skip_too_short", {
                        "run_id": run_id,
                        "subject": subject,
                        "sender": sender,
                        "content_length": len(content)
                    })
                    continue

                # Extract publisher name with body preview for better LLM verification
                body_preview = content[:500] if len(content) > 500 else content
                publisher_name = extract_publisher_name(
                    sender,
                    subject=subject,
                    list_id=list_id,
                    body_preview=body_preview
                )

                # Use Gmail URL for all items
                url = f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}"

                # Create item in same format as RSS
                item = {
                    "id": f"gmail:{msg['id']}",
                    "url": url,
                    "title": subject,
                    "content": content,
                    "published": received_date.isoformat(),
                    "publishers": [publisher_name],
                    "source_types": ["newsletter"],
                    "ingestion_tier": 2,  # Newsletters are Tier 2 (between news and research)
                    "fetch_full_article": False,  # Already have full content
                    "content_source": "gmail",
                    "discovered_at": run_id
                }

                items.append(item)

                log("gmail", "message_processed", {
                    "run_id": run_id,
                    "message_index": idx,
                    "subject": subject,
                    "sender": sender,
                    "content_length": len(content)
                })

            except Exception as e:
                skipped["parse_error"] += 1
                log("gmail", "parse_error", {
                    "run_id": run_id,
                    "message_id": msg['id'],
                    "error": str(e)
                })
                continue

        log("gmail", "fetch_complete", {
            "run_id": run_id,
            "total_processed": len(messages),
            "items_extracted": len(items),
            "skipped": skipped,
            "success_rate": round(len(items) / len(messages) * 100, 2) if messages else 0
        })

        return items

    except HttpError as error:
        log("gmail", "api_error", {
            "run_id": run_id,
            "error": str(error)
        })
        raise


def main():
    """
    Standalone Gmail ingestion.
    Fetches emails and saves to data/gmail_sources.json
    """
    run_id = f"gmail_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"📧 Starting Gmail ingestion (run_id: {run_id})")

    # Use centralized lookback period from briefing config
    lookback_days = get_lookback_days()
    print(f"Using lookback period: {lookback_days} days")

    items = fetch_emails(lookback_days=lookback_days, max_results=100, run_id=run_id)

    print(f"✓ Fetched {len(items)} newsletter items from Gmail")

    # Save to separate file (can be merged with RSS later)
    output_file = DATA_DIR / "gmail_sources.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(items, f, indent=2)

    print(f"💾 Saved to {output_file}")

    # Also append to raw_sources.json if it exists
    raw_sources_file = DATA_DIR / "raw_sources.json"
    if raw_sources_file.exists():
        with open(raw_sources_file) as f:
            existing = json.load(f)

        # Merge (remove duplicates by ID)
        existing_ids = {item['id'] for item in existing}
        new_items = [item for item in items if item['id'] not in existing_ids]

        merged = existing + new_items

        with open(raw_sources_file, 'w') as f:
            json.dump(merged, f, indent=2)

        print(f"📊 Merged with RSS: {len(existing)} existing + {len(new_items)} new = {len(merged)} total")

    return items


if __name__ == "__main__":
    main()
