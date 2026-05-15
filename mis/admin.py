from django.contrib import admin

from .models import ExpenseDetail, FeesDetail, Receipt


@admin.register(FeesDetail)
class FeesDetailAdmin(admin.ModelAdmin):
    list_display = ("date", "client", "pan_no", "fees_amount", "gst_amount", "total_amount")
    list_select_related = ("client",)
    search_fields = ("client__client_name", "client__client_id", "pan_no")
    list_filter = ("date",)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("date", "client", "pan_no", "amount_received")
    list_select_related = ("client",)
    search_fields = ("client__client_name", "client__client_id", "pan_no")
    list_filter = ("date",)


@admin.register(ExpenseDetail)
class ExpenseDetailAdmin(admin.ModelAdmin):
    list_display = ("date", "client", "pan_no", "expenses_paid", "notes")
    list_select_related = ("client",)
    search_fields = ("client__client_name", "client__client_id", "pan_no", "notes")
    list_filter = ("date",)

