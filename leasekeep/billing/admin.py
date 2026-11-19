from django.contrib import admin

from .models import LeaseCharge, Payment, StripeEvent


@admin.register(LeaseCharge)
class LeaseChargeAdmin(admin.ModelAdmin):
    list_display = ["lease", "label", "due_date", "amount", "waived"]
    list_filter = ["kind", "waived"]
    date_hierarchy = "due_date"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["lease", "amount", "received_on", "method", "status", "reference"]
    list_filter = ["method", "status"]
    date_hierarchy = "received_on"
    search_fields = ["reference", "stripe_checkout_session_id", "lease__lease_number"]


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "received_at"]
    readonly_fields = ["event_id", "event_type", "received_at"]
