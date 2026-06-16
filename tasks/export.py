"""CSV export for task lists."""

from __future__ import annotations

import csv

from django.http import HttpResponse

from .listing import TaskListFilters, filters_query_string, get_filtered_tasks, prepare_task_list_rows
from .user_labels import user_person_name
from .verifiers import format_task_verifier_names


def task_list_csv_response(
    request,
    user,
    filters: TaskListFilters,
    *,
    base_qs=None,
    filename: str = "tasks.csv",
    show_submitter_verifier_names: bool = False,
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
            "Description",
            "Period key",
            "Frequency",
            "Period",
            "Next period",
            "Status",
            "Due",
            "Users",
            "Verifier",
            "Submitted",
            *(
                ["Submitted by"]
                if show_submitter_verifier_names
                else []
            ),
            "Approved",
            *(
                ["Approved by"]
                if show_submitter_verifier_names
                else []
            ),
            "Billable",
            "Fees",
            "Currency",
        ]
    )

    for row in rows:
        t = row.task
        p = row.period
        csv_row = [
            row.created_date,
            t.client.client_name,
            t.client_id,
            t.display_title,
            t.description or "",
            t.period_key,
            p.frequency or "",
            p.period or "",
            p.next_period or "",
            t.get_status_display(),
            t.due_date.strftime("%d-%b-%Y") if t.due_date else "",
            row.assignee_names,
            format_task_verifier_names(t),
            row.submitted_date,
        ]
        if show_submitter_verifier_names:
            csv_row.append(row.submitted_by_name)
        csv_row.append(row.verified_date)
        if show_submitter_verifier_names:
            csv_row.append(row.verified_by_name)
        csv_row.extend(
            [
                "Yes" if t.is_billable else "No",
                str(t.fees_amount) if t.fees_amount is not None else "",
                t.currency,
            ]
        )
        writer.writerow(csv_row)
    return response
