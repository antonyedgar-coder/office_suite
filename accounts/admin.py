from django.contrib import admin

from .models import Account, AccountGroup, InvoiceNumberSeq, ReceiptAllocation, RecoveryAllocation, Voucher, VoucherLine


class VoucherLineInline(admin.TabularInline):
    model = VoucherLine
    extra = 0


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "main_head", "system_key", "is_active"]
    search_fields = ["name"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["name", "group", "gstin", "pan", "opening_balance", "client", "is_active"]
    search_fields = ["name", "gstin", "pan"]


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ["number", "voucher_type", "date", "series"]
    inlines = [VoucherLineInline]


@admin.register(InvoiceNumberSeq)
class InvoiceNumberSeqAdmin(admin.ModelAdmin):
    list_display = ["series", "year", "month", "last_value"]


@admin.register(ReceiptAllocation)
class ReceiptAllocationAdmin(admin.ModelAdmin):
    list_display = ["receipt", "party", "against", "amount", "is_opening", "is_advance"]


@admin.register(RecoveryAllocation)
class RecoveryAllocationAdmin(admin.ModelAdmin):
    list_display = ["invoice", "payment_line", "amount"]
