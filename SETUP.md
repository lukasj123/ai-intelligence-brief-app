# Setup Guide

Complete setup instructions for the AI News Briefings App.

## Prerequisites

- Python 3.10+
- Gmail account (for newsletter ingestion and email delivery) and cloud console enabled
- OpenAI API key

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:

```bash
OPENAI_API_KEY=sk-proj-your-key-here
```

**Note**: Email delivery uses Gmail API (same as ingestion), so no separate email credentials needed! OAuth means no Gmail API key.

## 3. Configure Gmail API (for ingestion AND email delivery)

The app uses Gmail API for both reading newsletters and sending briefings.

### Enable Gmail API

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the Gmail API:
   - Search for "Gmail API" in the search bar
   - Click "Enable"

### Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Configure consent screen if prompted:
   - User Type: External
   - App name: "AI News Briefings"
   - Add your email as a test user
   - Scopes: Add `gmail.readonly` and `gmail.send`
4. Application type: **Desktop app**
5. Name: "AI News Briefings Desktop"
6. Click **Create**

### Download Credentials

1. Click the download button next to your OAuth client
2. Save the JSON file as `.credentials/gmail_credentials.json`

```bash
mkdir -p .credentials
# Move downloaded file to:
# .credentials/gmail_credentials.json
```

### First-Time Authentication

Run Gmail ingestion once to authenticate (grants both read and send permissions):

```bash
python -m ingest.gmail
```

This will:
1. Open your browser for Google authorization
2. Ask for permissions to read and send emails
3. Save the refresh token to `.credentials/gmail_token.json`
4. **This same token is used for both ingestion and delivery** - authenticate once, use everywhere!

## 4. Configure Delivery Settings

Copy the delivery config example:

```bash
cp config/delivery_config.json.example config/delivery_config.json
```

Edit `config/delivery_config.json`:

```json
{
  "enabled": true,
  "recipient_email": "your-email@example.com",
  "sender_email": "your-gmail@gmail.com",
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "frequency": "weekly"
}
```

## 5. Test the Pipeline

### Test RSS Ingestion

```bash
python -m ingest.rss
```

Expected: Creates `data/raw_sources.json` with articles from RSS feeds.

### Test Gmail Ingestion

```bash
python -m ingest.gmail
```

Expected: Fetches newsletters and merges with `data/raw_sources.json`.

### Test Analysis Pipeline

```bash
python run.py
```

Expected: Analyzes articles and prints briefing to console.

### Test Email Delivery

```bash
python -m deliver.email
```

Expected: Sends test briefing to your configured email.

### Test Complete Pipeline

```bash
python briefing_pipeline.py
```

Expected: Runs full pipeline (Gmail + RSS → Analysis → Email delivery).

## 6. Using the Control Panel

Launch the Streamlit control panel:

```bash
streamlit run ui/control.py
```

Features:
- **Configuration Tab**: Customize analyzer and reviewer prompts
- **Pipeline Control Tab**: Run ingestion, analysis, and complete pipeline
- **Results Tab**: View briefing output and stats

## 7. Automated Scheduling (GitHub Actions)

### Setup GitHub Secrets

1. Push your code to GitHub (ensure `.credentials/` is gitignored!)
2. Go to **Settings** → **Secrets and variables** → **Actions**
3. Add the following secrets:

| Secret Name | Value |
|-------------|-------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `GMAIL_CREDENTIALS` | Contents of `.credentials/gmail_credentials.json` |
| `GMAIL_TOKEN` | Contents of `.credentials/gmail_token.json` |
| `ANALYZER_INSTRUCTIONS` | (Optional) Custom analyzer focus |
| `REVIEWER_FOCUS` | (Optional) Custom reviewer criteria |
| `LOOKBACK_DAYS` | (Optional) Default: 7 |

### Trigger Automated Runs

The workflow runs automatically every Monday at 9 AM UTC.

To run manually:
1. Go to **Actions** tab in GitHub
2. Select "Weekly AI News Briefing"
3. Click **Run workflow**

### Customize Schedule

Edit `.github/workflows/weekly-briefing.yml`:

```yaml
schedule:
  - cron: '0 9 * * 1'  # Monday at 9 AM UTC
```

Change to your preferred schedule:
- Daily at 8 AM: `'0 8 * * *'`
- Every 3 days: `'0 9 */3 * *'`
- Twice weekly (Mon/Thu): `'0 9 * * 1,4'`
