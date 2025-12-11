# Railway Data Sync Scripts

These scripts help you pull data from your Railway production databases (PostgreSQL and Redis) to your local environment for testing.

## Prerequisites

### Install Required Tools

**macOS:**
```bash
brew install postgresql redis
```

**Ubuntu/Debian:**
```bash
sudo apt-get install postgresql-client redis-tools
```

### Get Railway Connection Strings

1. **PostgreSQL Connection String:**
   - Go to Railway Dashboard → Your PostgreSQL Service
   - Click "Connect" → "Public Networking"
   - Copy the "Connection String" (starts with `postgresql://`)

2. **Redis Connection String:**
   - Go to Railway Dashboard → Your Redis Service
   - Click "Connect" → "Public Networking"
   - Copy the "Connection String" (starts with `redis://`)

### Add to .env File

Add these variables to your `.env` file:

```bash
# Railway Production Database URLs (for syncing data)
RAILWAY_DATABASE_URL=postgresql://user:password@host:port/database
RAILWAY_REDIS_URL=redis://user:password@host:port/db
```

**Note:** These are separate from your local `DATABASE_URL` and `REDIS_URL` which point to your local Docker containers.

## Usage

### Option 1: Sync Everything (Recommended)

This will dump both databases from Railway and restore them locally:

```bash
./scripts/sync_from_railway.sh
```

This script will:
1. Dump PostgreSQL from Railway
2. Dump Redis from Railway
3. Restore PostgreSQL to your local Docker database
4. Restore Redis to your local Docker Redis

### Option 2: Individual Operations

**Dump PostgreSQL from Railway:**
```bash
./scripts/dump_railway_postgres.sh
```

**Dump Redis from Railway:**
```bash
./scripts/dump_railway_redis.sh
```

**Restore PostgreSQL locally:**
```bash
./scripts/restore_postgres.sh backups/railway_postgres_YYYYMMDD_HHMMSS.sql
# OR for custom format:
./scripts/restore_postgres.sh backups/railway_postgres_YYYYMMDD_HHMMSS.dump
```

**Restore Redis locally:**
```bash
./scripts/restore_redis.sh backups/railway_redis_YYYYMMDD_HHMMSS.rdb
```

## What Gets Synced

### PostgreSQL
- All grants
- All scrape logs
- All users and authentication data
- All companies
- All grant matches
- All other Django models

### Redis
- Celery task results
- Cache data
- Session data (if stored in Redis)
- Any other Redis keys

## After Syncing

1. **Start your local environment:**
   ```bash
   docker compose -f docker-compose.yml.local up
   ```

2. **Access the application:**
   - Main app: http://localhost:8000
   - Admin: http://localhost:8000/admin
   - Use the same login credentials from production

3. **You'll see:**
   - All production grants
   - All production scrape logs
   - All production users (you can log in with production credentials)
   - All production companies

## Backup Files

All dumps are saved in the `backups/` directory with timestamps:
- `railway_postgres_YYYYMMDD_HHMMSS.sql` - SQL format dump
- `railway_postgres_YYYYMMDD_HHMMSS.dump` - Custom format dump (smaller, faster)
- `railway_redis_YYYYMMDD_HHMMSS.rdb` - Redis RDB dump

**Note:** The `backups/` directory is in `.gitignore` and won't be committed to git.

## Troubleshooting

### "pg_dump: command not found"
Install PostgreSQL client tools (see Prerequisites above).

### "redis-cli: command not found"
Install Redis tools (see Prerequisites above).

### "Cannot connect to Railway database"
- Check that `RAILWAY_DATABASE_URL` is correct in your `.env`
- Ensure Railway PostgreSQL has "Public Networking" enabled
- Check that your IP is whitelisted (if required)

### "Cannot connect to Railway Redis"
- Check that `RAILWAY_REDIS_URL` is correct in your `.env`
- Ensure Railway Redis has "Public Networking" enabled
- Check that your IP is whitelisted (if required)

### "Permission denied" when restoring
Make sure Docker containers are running:
```bash
docker compose -f docker-compose.yml.local up -d db redis
```

## Security Notes

⚠️ **Important:**
- Never commit your `.env` file with production credentials
- The `backups/` directory contains production data and is gitignored
- Be careful when sharing backup files - they contain sensitive data
- Consider encrypting backup files if storing them long-term

