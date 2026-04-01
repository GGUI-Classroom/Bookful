# Bookful

Library checkout tracker for teachers using Flask + PostgreSQL.

## Local Setup

1. Create and activate virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` at project root with:

```env
SECRET_KEY=replace-with-a-long-random-string
DATABASE_URL=postgresql://username:password@host:5432/database_name
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

## Render Deploy

1. Push this project to GitHub.
2. In Render, create service from `render.yaml`.
3. In Render dashboard for web service, set:
   - `SECRET_KEY` to a strong random value.
4. `DATABASE_URL` is auto-linked from the managed Render Postgres defined in `render.yaml`.
5. After first deploy, run migrations in Render Shell:

```bash
flask --app run.py db upgrade
```

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
