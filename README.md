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
7. Set `REPORT_ADMIN_EMAIL=g.gui.cmpny@gmail.com` to grant that signed-in Bookful account access to the broadcast composer.
8. In cron-job.org, create an hourly `POST` request to:

```text
https://your-bookful-app.onrender.com/reports/tasks/send-weekly
```

Add this request header, substituting the same secret stored in Render:

```text
Authorization: Bearer your-report-job-secret
```

The endpoint is safe to call hourly. It checks each opted-in teacher's weekday, hour, time zone, and last delivery before sending. Teachers manage their preference under **Email Reports**, and the manual test-send button does not alter their weekly schedule.

### Administrator announcements

Only the authenticated Bookful account whose email exactly matches `REPORT_ADMIN_EMAIL` can access `/reports/broadcast`; authorization is checked on the server for every request. Sending also requires that account's current Bookful password and an explicit confirmation checkbox. Messages use a fixed safe design system rather than accepting custom HTML, are delivered separately to each teacher so recipient addresses are never shared, reject identical submissions within five minutes, and create a database audit record with sent/failed totals.

### Teacher email verification

New teacher accounts must enter a six-digit code sent through the configured Gmail sender before they can access Bookful. Codes expire after 15 minutes, allow five attempts, have a 60-second resend cooldown, and are stored only as keyed hashes. The verification screen and email remind teachers to check junk or spam folders. Student portal accounts are not part of this flow.

When verification columns are added to an existing database, all teacher rows that already existed are automatically stamped as verified. No existing teacher accounts are removed or forced through the new-code flow. Administrator broadcasts and scheduled reports include verified teachers only.

The **Send test report** action is limited to one successful message per teacher per local calendar day. A database uniqueness constraint enforces the limit even if requests arrive simultaneously; failed deliveries release the reservation so the teacher can retry.
