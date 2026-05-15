from django.contrib import admin

from .models import Dir3Kyc


@admin.register(Dir3Kyc)
class Dir3KycAdmin(admin.ModelAdmin):
    list_display = ("date_done", "director", "srn", "created_at")
    list_select_related = ("director",)
    search_fields = ("director__client_name", "director__din", "director__client_id", "srn")
    list_filter = ("date_done",)
