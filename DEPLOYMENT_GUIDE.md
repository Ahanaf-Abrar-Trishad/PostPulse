# DEPLOYMENT_GUIDE.md

## Local Deployment (Primary v1)

1. Install dependencies and Playwright browser:

```bash
pip install -r requirements.txt
playwright install chromium
```

2. Configure `.env` and `config/config.yaml`.
3. Initialize DB:

```bash
python -m app.main init-db
```

4. Run scheduler:

```bash
python -m app.main schedule
```

## Docker Deployment

1. Set values in `.env`.
2. Start PostgreSQL:

```bash
docker compose up -d db
```

3. Initialize schema:

```bash
docker compose run --rm app python -m app.main init-db
```

4. Execute workflow:

```bash
docker compose run --rm app python -m app.main run-daily
```

## Cloud Deployment (Reference)

This v1 project is local-first. For cloud adaptation:

- Build and push Docker image.
- Use managed PostgreSQL.
- Use managed scheduler:
  - AWS EventBridge + ECS task
  - Azure Container Apps Jobs
  - GCP Cloud Scheduler + Cloud Run Job
- Store secrets in cloud secret manager.
- Route logs to central monitoring.

## Scheduling in Cloud

Map jobs to these cron expressions (UTC):

- Discover: `0 1 * * *`
- Scrape: `0 2 * * *`
- Analyze: `0 3 * * *`
- Generate: `30 3 * * *`

## Operational Checklist

- Confirm token scopes for LinkedIn and Facebook.
- Confirm webhook endpoint availability.
- Monitor `logs/socialintel.log` and run history via `/runs`.
- Track DB growth and retention policy for post snapshots.
