from django.urls import path

from . import views

urlpatterns = [
    path("api/suggest-directors/", views.api_suggest_directors, name="reports_api_suggest_directors"),
    path("api/suggest-companies/", views.api_suggest_companies, name="reports_api_suggest_companies"),
    path("", views.report_index, name="reports_index"),
    path("client-master/", views.client_master_report, name="reports_client_master"),
    path(
        "client-master/download.csv",
        views.client_master_report_csv,
        name="reports_client_master_csv",
    ),
    path("mis/", views.mis_report, name="reports_mis"),
    path("mis/download.csv", views.mis_report_csv, name="reports_mis_csv"),
    path("director-mapping/", views.director_mapping_report, name="reports_director_mapping"),
    path(
        "director-mapping/download.csv",
        views.director_mapping_report_csv,
        name="reports_director_mapping_csv",
    ),
    path("dir3-kyc/", views.dir3kyc_report, name="reports_dir3kyc"),
    path("dir3-kyc/download.csv", views.dir3kyc_report_csv, name="reports_dir3kyc_csv"),

    # Backward-compatible links (old MIS report URLs)
    path("mis/period/", views.mis_report, name="reports_mis_period"),
    path("mis/client-wise/", views.mis_report, name="reports_mis_client_wise"),
    path("mis/type-wise/", views.mis_report, name="reports_mis_type_wise"),
]
