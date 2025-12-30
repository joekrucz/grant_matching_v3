# Slack Bot Integration

This app provides Slack webhook endpoints to fetch company information, filings, and grants.

## Setup

### 1. Environment Variables

Add these to your `.env` file or environment:

```bash
SLACK_SIGNING_SECRET=your_signing_secret_from_slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Migrations

```bash
python manage.py makemigrations slack_bot
python manage.py migrate
```

### 4. Configure Slack App

1. Go to https://api.slack.com/apps
2. Select your app
3. Go to **Event Subscriptions**:
   - Enable Events
   - Request URL: `https://yourdomain.com/slack/events`
   - Subscribe to bot events:
     - `app_mentions`
     - `message.channels` (optional)
     - `message.im` (for direct messages)
4. Go to **Slash Commands** (optional):
   - Create command: `/company-info`
   - Request URL: `https://yourdomain.com/slack/commands`
   - Description: "Get company filings and grants"
   - Usage hint: `[company_number]`

## Usage

### Direct Message
Send a company number to the bot:
```
12345678
```

### App Mention
Mention the bot in a channel:
```
@trellis-bot 12345678
```

### Slash Command
```
/company-info 12345678
```

## Response Format

The bot returns:
- Company details (name, status, type, SIC codes, address)
- Recent filings (last 5)
- Previous grants (last 5, if any)

## Endpoints

- `POST /slack/events` - Slack Events API webhook
- `POST /slack/commands` - Slack slash command handler

## Security

- All requests are verified using Slack's signing secret
- Signature verification prevents unauthorized requests
- CSRF is disabled for Slack endpoints (Slack doesn't send CSRF tokens)

