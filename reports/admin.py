from django.contrib import admin

from .models import ReportPolicy


@admin.register(ReportPolicy)
class ReportPolicyAdmin(admin.ModelAdmin):
    list_display = ("label",)
