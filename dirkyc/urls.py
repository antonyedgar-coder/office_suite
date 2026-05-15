from django.urls import path

from . import views

urlpatterns = [
    path("", views.dir3kyc_list, name="dirkyc_list"),
    path("new/", views.dir3kyc_create, name="dirkyc_create"),
    path("<int:pk>/delete/", views.dir3kyc_delete, name="dirkyc_delete"),
    path("<int:pk>/", views.dir3kyc_edit, name="dirkyc_edit"),
]
