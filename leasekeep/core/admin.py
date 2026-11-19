from django.contrib import admin
from django.db import models

from .models import Organization

admin.site.site_header = "Leasekeep administration"
admin.site.site_title = "Leasekeep"
admin.site.index_title = "Settings and records"


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}
    fieldsets = [
        (None, {"fields": ["name", "short_name", "address", "phone", "email", "website"]}),
        (
            "Stewardship policy",
            {
                "fields": [
                    "fiscal_year_start_month",
                    "default_monthly_lease_fee",
                    "lease_fee_due_day",
                    "grace_period_days",
                    "refinance_max_ltv_percent",
                    "occupancy_check_due_month",
                ]
            },
        ),
        ("Owner portal", {"fields": ["portal_welcome"]}),
    ]

    def has_add_permission(self, request):
        return not Organization.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
