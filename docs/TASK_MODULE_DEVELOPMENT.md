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

```bash
python manage.py create_recurring_tasks
```

Schedule via cron or your platform scheduler (e.g. once per day, Asia/Kolkata).

## Permissions

Assign via **User Management** → groups:

- Task groups / task masters: view, add, change
- Tasks: view, add, assign, change, verify, delete

Users in the Django group named **Admin** (plus superusers) receive in-app alerts when recurring task creation fails (e.g. inactive assignee).

## Local smoke test

1. `ENABLE_TASK_MODULE=1` in `.env`
2. `python manage.py migrate`
3. Grant your user task permissions (or use superuser)
4. Create task group → task master → assign first task to a client
5. `python manage.py test tasks`
