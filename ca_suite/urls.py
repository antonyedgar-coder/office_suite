import os
from pathlib import Path

from django.contrib import admin
from django.urls import path, include

from core import views as core_views


handler403 = core_views.permission_denied_view  # noqa: E501

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", core_views.login_view, name="login"),
    path("logout/", core_views.logout_view, name="logout"),
    path("masters/", include("masters.urls")),
    path("mis/", include("mis.urls")),
    path("dirkyc/", include("dirkyc.urls")),
    path("reports/", include("reports.urls")),
    path("", include("core.urls")),
]


def _build_business_rules_docx_on_reload() -> None:
    """Generate docs docx when dev server reloads after build trigger file is touched."""
    if os.environ.get("RUN_MAIN") != "true":
        return
    base = Path(__file__).resolve().parent.parent
    trigger = base / "docs" / ".build_docx_trigger"
    if not trigger.exists():
        return
    try:
        import importlib.util

        script = base / "docs" / "build_word_manual.py"
        spec = importlib.util.spec_from_file_location("build_word_manual", script)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.build()
    except Exception:
        pass


_build_business_rules_docx_on_reload()

