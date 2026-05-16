import logging

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


class ActivityLogMiddleware:
    """
    Records authenticated mutating requests and selected GET exports after a successful response.
    """

    _SAFE = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._maybe_record(request, response)
        except Exception:
            logger.exception("ActivityLogMiddleware failed")
        return response

    def _maybe_record(self, request, response):
        if not getattr(request.user, "is_authenticated", False):
            return

        path = request.path
        if (
            path.startswith("/static/")
            or path.startswith("/admin/")
            or path.startswith("/media/")
        ):
            return
        if path.startswith("/login") or path.startswith("/logout"):
            return

        match = getattr(request, "resolver_match", None)
        name = (getattr(match, "url_name", None) or "").lower()

        if name == "activity_log" and request.method == "GET":
            return

        status = response.status_code
        if status >= 400:
            return

        method = (request.method or "GET").upper()
        if method in self._SAFE:
            if method != "GET":
                return
            if not self._loggable_get(name):
                return

        from .activity_log import enrich_activity_log_description, log_activity_from_request

        q = request.META.get("QUERY_STRING", "")
        if q and len(q) < 400:
            desc = f"{method} {path}?{q}"
        else:
            desc = f"{method} {path}"

        desc = enrich_activity_log_description(request, desc)

        log_activity_from_request(
            user=request.user,
            request=request,
            method=method,
            path=path,
            status_code=status,
            description=desc,
        )

    @staticmethod
    def _loggable_get(url_name: str) -> bool:
        if "csv" in url_name:
            return True
        return url_name in {
            "client_import_template",
            "client_group_bulk_import_template",
            "director_mapping_bulk_import_template",
            "mis_bulk_import_template",
        }


class InactiveUserMiddleware:
    """Sign out users whose account was deactivated while they were logged in."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_active:
            logout(request)
            messages.error(
                request,
                "This account is inactive. Contact your administrator.",
            )
            return redirect("login")
        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    """
    Redirect authenticated users who must change password (first login after invite).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if not getattr(request.user, "force_password_change", False):
            return self.get_response(request)

        path = request.path
        if (
            path.startswith("/login")
            or path.startswith("/logout")
            or path.startswith("/static")
            or path.startswith("/admin")
            or path == "/account/first-password/"
        ):
            return self.get_response(request)

        return redirect("first_password_change")
