from django.contrib import admin
from django.urls import path, include

from core import views as core_views


handler403 = core_views.permission_denied_view

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

