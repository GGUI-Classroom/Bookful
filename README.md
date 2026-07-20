# Bookful

Library checkout tracker for teachers using Flask + Supabase Postgres.

## Local Setup

1. Create and activate virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` at project root with:

```env
SECRET_KEY=replace-with-a-long-random-string
DATABASE_URL=postgresql://postgres.project-ref:your-password@aws-0-region.pooler.supabase.com:5432/postgres
FLASK_ENV=development
```

4. Run migrations:

```bash
flask --app run.py db init
flask --app run.py db migrate -m "Initial schema"
flask --app run.py db upgrade
```

5. Start server:

```bash
flask --app run.py run
```

## Supabase Free Tier Setup

1. Go to https://supabase.com and create an account.
2. Create a new project.
   - Organization: use your personal organization unless you already have one.
   - Project name: `bookful` is fine.
   - Database password: generate and save a strong password. You will need it for `DATABASE_URL`.
   - Region: choose the closest region to your users and your Render service.
   - Pricing plan: Free.
3. Wait for Supabase to finish provisioning the project.
4. In Supabase, open **Project Settings > Database**.
5. Find **Connection string** and choose the **Session pooler** URI when deploying from Render free tier.
   - Supabase direct connections can require IPv6 availability.
   - The shared session pooler is usually the easiest fit for persistent Flask apps on IPv4-only hosting.
6. Copy the URI and replace `[YOUR-PASSWORD]` with the database password from step 2.
7. Use that full URI as this app's `DATABASE_URL`.
8. Keep Supabase Row Level Security settings as-is. This app connects as the database user through SQLAlchemy and does not use Supabase client-side table APIs.

## Render Deploy With Supabase

1. Push this project to GitHub.
2. In Render, create service from `render.yaml`.
3. In Render dashboard for web service, set:
   - `SECRET_KEY` to a strong random value.
   - `DATABASE_URL` to your Supabase session pooler connection string.
   - The Gmail reporting variables described below if email reports are enabled.
4. After first deploy, run migrations in Render Shell:

```bash
flask --app run.py db upgrade
```

This project also calls `db.create_all()` on startup as a first-deploy safety net, so an empty Supabase database can boot even before migration files exist.

## Core Routes

- `/auth/signup`
- `/auth/login`
- `/dashboard`
- `/classes/`
- `/classes/join/<join_code>`
- `/students/`
- `/books/`
- `/checkouts/new`
- `/checkouts/history`

## Gmail Weekly Reports

Bookful can send opt-in aggregate reports to each teacher's registered email through one dedicated Gmail account. Bookful users continue to use Bookful's normal login; only the sender account authorizes Google.

1. In Google Cloud, enable the Gmail API and create an OAuth Desktop client with only the `gmail.send` scope.
2. Download the OAuth client JSON outside the repository.
3. Install dependencies, then authorize the dedicated sender locally:

```bash
flask --app run.py gmail-authorize --credentials "C:\\path\\to\\client_secret.json" --sender bookfulreports@gmail.com
```

4. Add the four values printed by that command to Render:
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN`
   - `GMAIL_SENDER_EMAIL`
5. Set `PUBLIC_BASE_URL` to the deployed Bookful origin, without a trailing slash.
6. Set `REPORT_JOB_SECRET` to a separate long random value. Never reuse `SECRET_KEY`.
7. In cron-job.org, create an hourly `POST` request to:

```text
https://your-bookful-app.onrender.com/reports/tasks/send-weekly
```

Add this request header, substituting the same secret stored in Render:

```text
Authorization: Bearer your-report-job-secret
```

The endpoint is safe to call hourly. It checks each opted-in teacher's weekday, hour, time zone, and last delivery before sending. Teachers manage their preference under **Email Reports**, and the manual test-send button does not alter their weekly schedule.
