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
