"""CSV export for task lists."""

from __future__ import annotations

import csv

from django.http import HttpResponse

from .listing import TaskListFilters, filters_query_string, get_filtered_tasks, prepare_task_list_rows
from .user_labels import user_person_name


def task_list_csv_response(
    request,
    user,
    filters: TaskListFilters,
    *,
    base_qs=None,
    filename: str = "tasks.csv",
) -> HttpResponse:
    tasks = get_filtered_tasks(user, filters, base_qs=base_qs, limit=100_000)
    rows = prepare_task_list_rows(tasks, include_assignees=True)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(
        [
            "Created",
            "Client",
            "Client ID",
            "Task",
            "Period key",
            "Month",
            "Quarter",
            "Half",
            "Yearly",
            "3 years",
            "5 years",
            "Next period",
            "Status",
            "Due",
            "Users",
            "Verifier",
            "Submitted",
            "Submitted by",
            "Approved",
            "Approved by",
            "Billable",
            "Fees",
            "Currency",
        ]
    )

    for row in rows:
        t = row.task
        p = row.period
        writer.writerow(
            [
                row.created_date,
                t.client.client_name,
                t.client_id,
                t.display_title,
                t.period_key,
                p.month or "",
                p.quarter or "",
                p.half or "",
                p.yearly or "",
                p.span_3y or "",
                p.span_5y or "",
                p.next_period or "",
                t.get_status_display(),
                t.due_date.strftime("%d-%b-%Y") if t.due_date else "",
                row.assignee_names,
                user_person_name(t.verifier),
                row.submitted_date,
                row.submitted_by_name,
                row.verified_date,
                row.verified_by_name,
                "Yes" if t.is_billable else "No",
                str(t.fees_amount) if t.fees_amount is not None else "",
                t.currency,
            ]
        )
    return response
