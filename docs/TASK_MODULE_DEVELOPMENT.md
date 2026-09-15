# Task module development

## Branch

Work on `feature/task-assignment`. Do **not** merge to `main` until UAT sign-off.

## Feature flag

| Variable | Default | Effect |
|----------|---------|--------|
| `ENABLE_TASK_MODULE` | `0` / unset | When false, `tasks` app is not installed, URLs are not mounted, and task permissions are hidden from User Management. |

Set in `.env` (see `.env.example`):

```env
ENABLE_TASK_MODULE=1
```

Restart the Django process after changing the flag.

## DigitalOcean / production

Keep `ENABLE_TASK_MODULE=0` on App Platform until UAT is complete. Run migrations on deploy when you enable the flag.

## Daily recurring job

The first task for a client only **starts the schedule**. Later periods are created when this runs (once per IST day):

```bash
python manage.py create_recurring_tasks
```

This App Platform account **does not accept `jobs:` in the App Spec** (`unknown field "jobs"`) and has no Job resource type. Do **not** add `jobs:` to the spec.

Automation is **GitHub Actions** calling:

`POST https://office.antonyandco.com/tasks/internal/create-recurring-tasks/`

### Turn it on

1. Remove any `jobs:` block from the App Spec so the spec saves again.
2. Generate a long random string. Add App Platform env **`CRON_SECRET`** (same as other env vars, RUN_TIME is enough).
3. GitHub repo → **Settings → Secrets and variables → Actions** → secret **`CRON_SECRET`** (same string).
4. Deploy this code to `main`.
5. GitHub → **Actions → Create recurring tasks → Run workflow** to test. Response should include `"created"` / `"skipped"`.

The workflow runs daily at **00:05 IST**. It does not backfill missed days.

## Permissions

Assign via **User Management** → groups:

- Task groups / task masters: view, add, change
- Tasks: view, add, assign, change, verify, delete, reopen, manage task billing (Accounts)

Users in the Django group named **Admin** (plus superusers) receive in-app alerts when recurring task creation fails (e.g. inactive assignee).

### Task billing (Accounts)

- Only users with **Can manage task billing (Accounts)** can set billable, fees, bill raised, bill date, and remarks.
- **Bill raised** requires the task to be complete. Fees stay editable after the bill is raised.
- Recurring auto-create copies **billable + fees** from the latest non-cancelled task for the same client and master (not bill-raised).
- These amounts are a snapshot on the task. They are **not** posted to MIS Fees.
- Sidebar **Task billing** lists complete billable work: unbilled, bill raised, or all.

## Local smoke test

1. `ENABLE_TASK_MODULE=1` in `.env`
2. `python manage.py migrate`
3. Grant your user task permissions (or use superuser)
4. Create task group → task master → assign first task to a client
5. `python manage.py test tasks`
