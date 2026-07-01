import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from core.branch_access import client_allowed_for_user
from core.decorators import require_perm
from core.feature_flags import task_module_enabled
from core.ui_breadcrumbs import breadcrumbs as ui_breadcrumbs
from masters.models import Client
from masters.views import client_master_queryset_for_user

from .client_forms import ClientDocumentClientForm
from .models import (
    ClientDocument,
    ClientDocumentFolder,
    DocumentFolderTemplate,
    DocumentTypeTemplate,
    TaskMasterDocumentMapping,
)
from .services import (
    create_client_document_folders,
    delete_client_document,
    document_types_for_folder_json,
    folder_upload_meta_json,
    replace_client_document,
    existing_folder_template_ids,
    folder_templates_for_client,
    save_client_document,
)
from .periods import fy_choices
from .task_bridge import user_can_change_task_linked_document
from .task_services import upload_document_for_task
from .template_forms import DocumentFolderTemplateForm, DocumentTypeTemplateForm
from .forms import ClientDocumentReplaceForm, ClientDocumentUploadForm

try:
    from tasks.models import Task
except ImportError:
    Task = None


def _require_template_admin(request):
    if not (
        request.user.is_superuser
        or request.user.has_perm("documents.manage_document_templates")
    ):
        raise PermissionDenied


def _client_or_404(user, client_id: str) -> Client:
    client = get_object_or_404(
        client_master_queryset_for_user(user).filter(approval_status=Client.APPROVED),
        pk=client_id,
    )
    if not client_allowed_for_user(user, client):
        raise PermissionDenied
    return client


@login_required
def document_folder_template_list(request):
    _require_template_admin(request)
    rows = DocumentFolderTemplate.objects.annotate(type_count=Count("document_types")).order_by(
        "sort_order", "name"
    )
    return render(
        request,
        "documents/folder_template_list.html",
        {
            "rows": rows,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("Folder creation",),
            ),
        },
    )


@login_required
def document_type_template_list(request):
    _require_template_admin(request)
    q = (request.GET.get("q") or "").strip()
    rows = DocumentTypeTemplate.objects.select_related("folder").annotate(
        doc_count=Count("uploads"),
    ).order_by(
        "folder__sort_order",
        "sort_order",
        "name",
    )
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(folder__name__icontains=q))
    return render(
        request,
        "documents/document_type_template_list.html",
        {
            "rows": rows,
            "q": q,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("File creation",),
            ),
        },
    )


@login_required
def document_folder_template_create(request):
    _require_template_admin(request)
    if request.method == "POST":
        form = DocumentFolderTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Folder created.")
            return redirect("document_folder_template_list")
    else:
        form = DocumentFolderTemplateForm()
    return render(
        request,
        "documents/folder_template_form.html",
        {
            "form": form,
            "title": "New folder",
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("Folder creation", "document_folder_template_list"),
                ("New folder",),
            ),
        },
    )


@login_required
def document_folder_template_edit(request, pk: int):
    _require_template_admin(request)
    obj = get_object_or_404(DocumentFolderTemplate, pk=pk)
    if request.method == "POST":
        form = DocumentFolderTemplateForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Folder updated.")
            return redirect("document_folder_template_list")
    else:
        form = DocumentFolderTemplateForm(instance=obj)
    return render(
        request,
        "documents/folder_template_form.html",
        {
            "form": form,
            "title": f"Edit folder — {obj.name}",
            "folder": obj,
            "can_delete_folder": obj.is_deletable,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("Folder creation", "document_folder_template_list"),
                (obj.name,),
            ),
        },
    )


@login_required
def document_folder_template_delete(request, pk: int):
    _require_template_admin(request)
    obj = get_object_or_404(DocumentFolderTemplate, pk=pk)
    if obj.is_system_folder:
        messages.error(
            request,
            "Supporting Documents and KYC Documents are system folders and cannot be deleted.",
        )
        return redirect("document_folder_template_list")
    file_type_count = obj.document_types.count()
    if request.method == "POST":
        if file_type_count:
            messages.error(
                request,
                "This folder cannot be deleted while file types are still mapped to it. "
                "Delete those file types under File creation first.",
            )
            return redirect("document_folder_template_edit", pk=pk)
        name = obj.name
        try:
            obj.delete()
        except ProtectedError:
            messages.error(
                request,
                "This folder cannot be deleted because clients already have this folder "
                "provisioned or files linked to it. Mark the folder inactive instead.",
            )
            return redirect("document_folder_template_edit", pk=pk)
        messages.success(request, f"Folder deleted: {name}.")
        return redirect("document_folder_template_list")
    return render(
        request,
        "documents/folder_template_delete_confirm.html",
        {
            "folder": obj,
            "file_type_count": file_type_count,
            "can_delete": obj.is_deletable,
            "client_folder_count": ClientDocumentFolder.objects.filter(template=obj).count(),
            "active_doc_count": ClientDocument.objects.filter(
                folder__template=obj,
                status=ClientDocument.STATUS_ACTIVE,
            ).count(),
            "task_link_count": TaskMasterDocumentMapping.objects.filter(folder=obj).count(),
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("Folder creation", "document_folder_template_list"),
                ("Delete folder",),
            ),
        },
    )


@login_required
def document_type_template_delete(request, pk: int):
    _require_template_admin(request)
    obj = get_object_or_404(DocumentTypeTemplate.objects.select_related("folder"), pk=pk)
    doc_count = obj.uploads.count()
    if request.method == "POST":
        if doc_count:
            messages.error(
                request,
                "This file type cannot be deleted while documents are still saved under it. "
                "Remove those files first, or mark the file type inactive instead.",
            )
            return redirect("document_type_template_edit", pk=pk)
        name = obj.name
        folder_name = obj.folder.name
        obj.delete()
        messages.success(request, f"File type deleted: {folder_name} — {name}.")
        return redirect("document_type_template_list")
    return render(
        request,
        "documents/document_type_template_delete_confirm.html",
        {
            "file_type": obj,
            "doc_count": doc_count,
            "can_delete": obj.is_deletable,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("File creation", "document_type_template_list"),
                ("Delete file type",),
            ),
        },
    )


@login_required
def document_type_template_create(request):
    _require_template_admin(request)
    folder_id = (request.GET.get("folder") or "").strip()
    initial_folder = int(folder_id) if folder_id.isdigit() else None
    if request.method == "POST":
        form = DocumentTypeTemplateForm(request.POST, folder_id=initial_folder)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                messages.error(
                    request,
                    "Could not save this file type — a duplicate entry may exist in this folder. "
                    "Try a different name.",
                )
            else:
                messages.success(request, "File type created.")
                return redirect("document_type_template_list")
    else:
        form = DocumentTypeTemplateForm(folder_id=initial_folder)
    return render(
        request,
        "documents/document_type_template_form.html",
        {
            "form": form,
            "title": "New file type",
            "can_delete_file_type": False,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("File creation", "document_type_template_list"),
                ("New file type",),
            ),
        },
    )


@login_required
def document_type_template_edit(request, pk: int):
    _require_template_admin(request)
    obj = get_object_or_404(DocumentTypeTemplate.objects.select_related("folder"), pk=pk)
    if request.method == "POST":
        form = DocumentTypeTemplateForm(request.POST, instance=obj)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                messages.error(
                    request,
                    "Could not save this file type — a duplicate entry may exist in this folder. "
                    "Try a different name.",
                )
            else:
                messages.success(request, "File type updated.")
                return redirect("document_type_template_list")
    else:
        form = DocumentTypeTemplateForm(instance=obj)
    return render(
        request,
        "documents/document_type_template_form.html",
        {
            "form": form,
            "title": f"Edit file — {obj.name}",
            "file_type": obj,
            "can_delete_file_type": obj.is_deletable,
            "breadcrumbs": ui_breadcrumbs(
                ("Settings", "settings_hub"),
                ("File creation", "document_type_template_list"),
                (obj.name,),
            ),
        },
    )


def _doc_breadcrumbs(*parts):
    return ui_breadcrumbs(("Documents", "document_file_list"), *parts)


def _document_action_redirect(request, *, default: str = "document_file_list"):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
    ):
        return redirect(next_url)
    return redirect(default)


def _active_document_or_404(user, pk: int) -> ClientDocument:
    doc = get_object_or_404(
        ClientDocument.objects.select_related("client", "folder__template", "document_type"),
        pk=pk,
        status=ClientDocument.STATUS_ACTIVE,
    )
    if not client_allowed_for_user(user, doc.client):
        raise PermissionDenied
    if not doc.file:
        raise Http404
    return doc


def _document_file_response(doc: ClientDocument, *, inline: bool) -> FileResponse:
    try:
        handle = doc.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    filename = doc.generated_filename
    if inline:
        response = FileResponse(handle, as_attachment=False, filename=filename)
        content_type, _ = mimetypes.guess_type(filename)
        if content_type:
            response["Content-Type"] = content_type
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
    return FileResponse(handle, as_attachment=True, filename=filename)


@login_required
@require_perm("documents.view_clientdocument")
def document_file_list(request):
    from core.branch_access import approved_clients_for_user

    allowed_clients = approved_clients_for_user(request.user).order_by("client_name")
    allowed_ids = allowed_clients.values_list("pk", flat=True)

    client_id = (request.GET.get("client") or "").strip()
    folder_template_id = (request.GET.get("folder_template") or "").strip()
    doc_type_id = (request.GET.get("doc_type") or "").strip()
    fy_filter = (request.GET.get("fy") or "").strip()

    qs = (
        ClientDocument.objects.filter(status=ClientDocument.STATUS_ACTIVE)
        .select_related(
            "client",
            "folder__template",
            "document_type",
            "uploaded_by",
        )
        .order_by("-uploaded_at")
    )
    qs = qs.filter(client_id__in=allowed_ids)
    if client_id:
        qs = qs.filter(client_id=client_id)
    if folder_template_id.isdigit():
        qs = qs.filter(folder__template_id=int(folder_template_id))
    if doc_type_id.isdigit():
        qs = qs.filter(document_type_id=int(doc_type_id))
    if fy_filter:
        qs = qs.filter(
            Q(period_key__startswith=f"FY{fy_filter}")
            | Q(financial_year=fy_filter)
        )

    folder_choices = (
        DocumentFolderTemplate.objects.filter(
            is_active=True,
            client_folders__client_id__in=allowed_ids,
        )
        .distinct()
        .order_by("sort_order", "name")
    )
    doc_type_choices = (
        DocumentTypeTemplate.objects.filter(
            is_active=True,
            folder__is_active=True,
            folder__client_folders__client_id__in=allowed_ids,
        )
        .select_related("folder")
        .distinct()
        .order_by("folder__sort_order", "sort_order", "name")
    )

    selected_client_label = ""
    if client_id:
        match_client = allowed_clients.filter(client_id=client_id).first()
        if match_client:
            selected_client_label = f"{match_client.client_name} — {match_client.client_id}"

    selected_folder_label = ""
    if folder_template_id.isdigit():
        match_folder = folder_choices.filter(pk=int(folder_template_id)).first()
        if match_folder:
            selected_folder_label = match_folder.name

    selected_doc_type_label = ""
    if doc_type_id.isdigit():
        match_type = doc_type_choices.filter(pk=int(doc_type_id)).first()
        if match_type:
            selected_doc_type_label = f"{match_type.folder.name} — {match_type.name}"

    client_filter_options = [
        {
            "id": c.client_id,
            "label": f"{c.client_name} — {c.client_id}",
            "search": f"{c.client_name} {c.client_id} {c.pan or ''}".lower(),
        }
        for c in allowed_clients
    ]
    folder_filter_options = [
        {"id": str(f.pk), "label": f.name, "search": f.name.lower()}
        for f in folder_choices
    ]
    doc_type_filter_options = [
        {
            "id": str(dt.pk),
            "label": f"{dt.folder.name} — {dt.name}",
            "search": f"{dt.folder.name} {dt.name}".lower(),
        }
        for dt in doc_type_choices
    ]

    return render(
        request,
        "documents/document_file_list.html",
        {
            "rows": qs[:500],
            "filter_client_id": client_id,
            "filter_folder_template_id": folder_template_id,
            "filter_doc_type_id": doc_type_id,
            "filter_fy": fy_filter,
            "selected_client_label": selected_client_label,
            "selected_folder_label": selected_folder_label,
            "selected_doc_type_label": selected_doc_type_label,
            "client_filter_options": client_filter_options,
            "folder_filter_options": folder_filter_options,
            "doc_type_filter_options": doc_type_filter_options,
            "client_choices": allowed_clients,
            "folder_choices": folder_choices,
            "doc_type_choices": doc_type_choices,
            "fy_choices": fy_choices(),
            "breadcrumbs": _doc_breadcrumbs(("View / download files",)),
        },
    )


@login_required
@require_perm("documents.add_clientdocument")
def client_document_upload_pick(request):
    if request.method == "POST":
        form = ClientDocumentClientForm(request.POST, user=request.user)
        if form.is_valid():
            return redirect("client_document_upload", client_id=form.cleaned_data["client"].pk)
    else:
        form = ClientDocumentClientForm(user=request.user)
    return render(
        request,
        "documents/client_document_pick.html",
        {
            "form": form,
            "title": "Upload file — select client",
            "continue_url_name": "client_document_upload_pick",
            "breadcrumbs": _doc_breadcrumbs(("Upload file",)),
        },
    )


@login_required
@require_perm("documents.view_clientdocument")
def client_folder_create(request):
    if not request.user.has_perm("documents.add_clientdocument"):
        raise PermissionDenied

    if request.method == "POST" and request.POST.get("action") == "select_client":
        form = ClientDocumentClientForm(request.POST, user=request.user)
        if form.is_valid():
            cid = form.cleaned_data["client"].pk
            return redirect(f"{reverse('client_folder_create')}?client_id={cid}")
        client_form = form
        return render(
            request,
            "documents/client_folder_create.html",
            {"client": None, "client_form": client_form, "folder_rows": [], "breadcrumbs": _doc_breadcrumbs(("Create folder",))},
        )

    client = None
    client_id = (request.GET.get("client_id") or request.POST.get("client_id") or "").strip()
    if client_id:
        client = get_object_or_404(
            client_master_queryset_for_user(request.user).filter(approval_status=Client.APPROVED),
            pk=client_id,
        )
        if not client_allowed_for_user(request.user, client):
            raise PermissionDenied

    if request.method == "POST" and request.POST.get("action") == "create_folders" and client:
        raw_ids = request.POST.getlist("folder_ids")
        template_ids = [int(x) for x in raw_ids if str(x).isdigit()]
        if not template_ids:
            messages.error(request, "Select at least one folder to create.")
        else:
            try:
                n = create_client_document_folders(client, template_ids, user=request.user)
                messages.success(request, f"Created {n} folder(s) for {client.client_name}.")
                if n:
                    return redirect("client_document_upload", client_id=client.client_id)
            except ValidationError as exc:
                messages.error(request, str(exc))
        return redirect(f"{reverse('client_folder_create')}?client_id={client.client_id}")

    client_form = ClientDocumentClientForm(user=request.user)
    if client:
        client_form.fields["client"].initial = client.pk
        name = client.client_name
        pan = (client.pan or "").upper()
        client_form.fields["client_search"].initial = f"{name} — {pan}" if pan else name

    folder_rows = []
    if client:
        existing = existing_folder_template_ids(client)
        for tmpl in folder_templates_for_client(client):
            folder_rows.append(
                {
                    "template": tmpl,
                    "already_created": tmpl.pk in existing,
                }
            )

    return render(
        request,
        "documents/client_folder_create.html",
        {
            "client": client,
            "client_form": client_form,
            "folder_rows": folder_rows,
            "breadcrumbs": _doc_breadcrumbs(("Create folder",)),
        },
    )


@login_required
@require_perm("documents.view_clientdocument")
def client_document_upload(request, client_id: str):
    if not request.user.has_perm("documents.add_clientdocument"):
        raise PermissionDenied
    client = _client_or_404(request.user, client_id)
    folders = ClientDocumentFolder.objects.filter(client=client).select_related("template")
    if not folders.exists():
        messages.warning(
            request,
            "No folders for this client yet. Use Documents → Create folder first.",
        )
        return redirect(f"{reverse('client_folder_create')}?client_id={client.client_id}")

    if request.method == "POST":
        form = ClientDocumentUploadForm(request.POST, request.FILES, client=client)
        if form.is_valid():
            try:
                save_client_document(
                    client=client,
                    folder=form.cleaned_data["folder"],
                    document_type=form.cleaned_data["document_type"],
                    period_key=form.cleaned_data["period_key"],
                    period_label=form.cleaned_data["period_label"],
                    uploaded_file=form.cleaned_data["file"],
                    user=request.user,
                    custom_display_name=form.cleaned_data.get("custom_display_name") or "",
                )
            except ValidationError as exc:
                if hasattr(exc, "message_dict"):
                    for field, errs in exc.message_dict.items():
                        for err in errs:
                            form.add_error(field if field != "__all__" else None, err)
                elif hasattr(exc, "messages"):
                    for err in exc.messages:
                        form.add_error(None, err)
                else:
                    form.add_error(None, str(exc))
            except Exception as exc:
                import logging

                logging.getLogger(__name__).exception("Client document upload failed")
                form.add_error(
                    None,
                    str(exc)
                    if settings.DEBUG
                    else "Upload failed. Cloud storage may be misconfigured — contact support.",
                )
            else:
                messages.success(request, "File uploaded.")
                return redirect("document_file_list")
    else:
        form = ClientDocumentUploadForm(client=client)

    return render(
        request,
        "documents/client_document_upload.html",
        {
            "client": client,
            "form": form,
            "types_json": document_types_for_folder_json(),
            "folder_meta_json": folder_upload_meta_json(client),
            "breadcrumbs": _doc_breadcrumbs(
                ("Upload file", "client_document_upload_pick"),
                (client.client_name,),
            ),
        },
    )


@login_required
@require_perm("documents.delete_clientdocument")
def client_document_delete(request, pk: int):
    doc = get_object_or_404(
        ClientDocument.objects.select_related(
            "client",
            "folder__template",
            "document_type",
        ),
        pk=pk,
        status=ClientDocument.STATUS_ACTIVE,
    )
    if not client_allowed_for_user(request.user, doc.client):
        raise PermissionDenied
    if request.method == "POST":
        label = doc.generated_filename
        try:
            delete_client_document(doc, user=request.user)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("document_file_list")
        messages.success(request, f"Deleted: {label}.")
        return _document_action_redirect(request)
    return render(
        request,
        "documents/client_document_confirm_delete.html",
        {
            "doc": doc,
            "breadcrumbs": _doc_breadcrumbs(
                ("View / download files",),
                ("Delete file",),
            ),
        },
    )


@login_required
@require_perm("documents.add_clientdocument")
def client_document_replace(request, pk: int):
    doc = get_object_or_404(
        ClientDocument.objects.select_related(
            "client",
            "folder__template",
            "document_type",
        ),
        pk=pk,
        status=ClientDocument.STATUS_ACTIVE,
    )
    if not client_allowed_for_user(request.user, doc.client):
        raise PermissionDenied

    if request.method == "POST":
        form = ClientDocumentReplaceForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                new_doc = replace_client_document(
                    doc,
                    uploaded_file=form.cleaned_data["file"],
                    user=request.user,
                )
            except ValidationError as exc:
                if hasattr(exc, "message_dict"):
                    for field, errs in exc.message_dict.items():
                        for err in errs:
                            form.add_error(field if field != "__all__" else None, err)
                elif hasattr(exc, "messages"):
                    for err in exc.messages:
                        form.add_error(None, err)
                else:
                    form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"File replaced: {new_doc.generated_filename} (v{new_doc.version}).",
                )
                return _document_action_redirect(request)
        for err in form.non_field_errors():
            messages.error(request, err)
        for field in form:
            for err in field.errors:
                messages.error(request, err)
        if not form.errors:
            messages.error(request, "Could not replace file. Choose a valid file and try again.")
        return _document_action_redirect(request)

    raise Http404


@login_required
@require_perm("documents.view_clientdocument")
def client_document_view(request, pk: int):
    doc = _active_document_or_404(request.user, pk)
    return _document_file_response(doc, inline=True)


@login_required
@require_perm("documents.view_clientdocument")
def client_document_download(request, pk: int):
    doc = _active_document_or_404(request.user, pk)
    return _document_file_response(doc, inline=False)


@login_required
@require_perm("documents.manage_document_templates")
def task_document_mapping_list(request):
    if Task is None or not task_module_enabled():
        raise Http404
    from tasks.models import TaskMaster

    rows = (
        TaskMasterDocumentMapping.objects.select_related(
            "task_master",
            "task_master__task_group",
            "folder",
        )
        .prefetch_related("folder__document_types")
        .order_by("task_master__task_group__name", "task_master__name", "sort_order")
    )
    q = (request.GET.get("q") or "").strip()
    if q:
        rows = rows.filter(
            Q(task_master__name__icontains=q)
            | Q(folder__name__icontains=q)
        )

    if request.method == "POST" and request.POST.get("action") == "add":
        task_master_id = request.POST.get("task_master")
        folder_id = request.POST.get("folder")
        if task_master_id.isdigit() and folder_id.isdigit():
            TaskMasterDocumentMapping.objects.get_or_create(
                task_master_id=int(task_master_id),
                folder_id=int(folder_id),
            )
            messages.success(request, "Folder linked to task type.")
        else:
            messages.error(request, "Select both a task type and a folder.")
        return redirect("task_document_mapping_list")

    if request.method == "POST" and request.POST.get("action") == "delete":
        mid = request.POST.get("mapping_id")
        if mid.isdigit():
            TaskMasterDocumentMapping.objects.filter(pk=int(mid)).delete()
            messages.success(request, "Mapping removed.")
        return redirect("task_document_mapping_list")

    task_masters = TaskMaster.objects.filter(is_active=True, archived_at__isnull=True).order_by(
        "task_group__sort_order", "name"
    )
    doc_types = DocumentTypeTemplate.objects.filter(
        is_active=True, folder__is_active=True
    ).select_related("folder").order_by("folder__sort_order", "name")
    folders = DocumentFolderTemplate.objects.filter(is_active=True).order_by("sort_order", "name")

    return render(
        request,
        "documents/task_document_mapping_list.html",
        {
            "rows": rows,
            "q": q,
            "task_masters": task_masters,
            "folders": folders,
            "doc_types": doc_types,
            "breadcrumbs": _doc_breadcrumbs(("Task → folder links",)),
        },
    )


def _task_for_document_upload(user, pk: int) -> "Task":
    if Task is None or not task_module_enabled():
        raise Http404
    from tasks.listing import tasks_queryset_for_user

    task = get_object_or_404(
        tasks_queryset_for_user(user).select_related("client", "task_master"),
        pk=pk,
    )
    if not client_allowed_for_user(user, task.client):
        raise PermissionDenied
    return task


@login_required
@require_perm("documents.add_clientdocument")
def task_document_upload(request, pk: int):
    task = _task_for_document_upload(request.user, pk)
    next_url = reverse("task_detail", kwargs={"pk": task.pk})

    if request.method != "POST":
        return redirect(next_url)

    doc_type_id = (request.POST.get("document_type_id") or "").strip()
    uploaded = request.FILES.get("file")
    if not doc_type_id.isdigit():
        messages.error(request, "Invalid file type.")
        return redirect(next_url)
    if not uploaded:
        messages.error(request, "Choose a file to upload.")
        return redirect(next_url)

    try:
        doc = upload_document_for_task(
            task,
            document_type_id=int(doc_type_id),
            uploaded_file=uploaded,
            user=request.user,
            custom_display_name=(request.POST.get("custom_display_name") or "").strip(),
        )
    except ValidationError as exc:
        if hasattr(exc, "messages"):
            for err in exc.messages:
                messages.error(request, err)
        else:
            messages.error(request, str(exc))
        return redirect(next_url)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("Task document upload failed")
        messages.error(
            request,
            str(exc) if settings.DEBUG else "Upload failed. Please try again or contact support.",
        )
        return redirect(next_url)

    messages.success(request, f"Uploaded {doc.generated_filename} (v{doc.version}).")
    return redirect(next_url)


@login_required
@require_perm("documents.change_clientdocument")
def client_document_rename(request, pk: int):
    doc = get_object_or_404(
        ClientDocument.objects.select_related(
            "client",
            "folder__template",
            "document_type",
            "task",
        ),
        pk=pk,
        status=ClientDocument.STATUS_ACTIVE,
    )
    if not client_allowed_for_user(request.user, doc.client):
        raise PermissionDenied
    if request.method != "POST":
        raise Http404
    new_name = (request.POST.get("display_name") or "").strip()
    try:
        from .services import rename_client_document

        doc = rename_client_document(doc, new_display_name=new_name, user=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return _document_action_redirect(request)
    messages.success(request, f"File renamed to: {doc.generated_filename}")
    return _document_action_redirect(request)
