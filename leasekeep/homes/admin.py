from django.contrib import admin

from .models import (
    Appraisal,
    CapitalImprovement,
    GroundLease,
    Home,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
    Subsidy,
)


class OwnershipInline(admin.TabularInline):
    model = Ownership
    extra = 0
    fields = ["household", "formula", "purchase_date", "purchase_price", "status", "sale_date"]
    show_change_link = True


class AppraisalInline(admin.TabularInline):
    model = Appraisal
    extra = 0


class SubsidyInline(admin.TabularInline):
    model = Subsidy
    extra = 0


@admin.register(Home)
class HomeAdmin(admin.ModelAdmin):
    list_display = ["street", "city", "state", "home_type", "tenure"]
    list_filter = ["home_type", "tenure", "city"]
    search_fields = ["address_line1", "address_line2", "city", "parcel_id"]
    inlines = [OwnershipInline, AppraisalInline, SubsidyInline]


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ["name", "primary_contact", "email", "household_size", "ami_percent_at_purchase"]
    search_fields = ["name", "primary_contact", "co_owners", "email"]
    raw_id_fields = ["portal_user"]


class LeaseInline(admin.StackedInline):
    model = GroundLease
    extra = 0


@admin.register(Ownership)
class OwnershipAdmin(admin.ModelAdmin):
    list_display = ["home", "household", "formula", "purchase_date", "purchase_price", "status"]
    list_filter = ["status", "formula"]
    search_fields = ["home__address_line1", "household__name"]
    inlines = [LeaseInline]


@admin.register(GroundLease)
class GroundLeaseAdmin(admin.ModelAdmin):
    list_display = ["lease_number", "ownership", "start_date", "monthly_fee", "ended_on"]
    search_fields = ["lease_number", "ownership__home__address_line1"]


@admin.register(CapitalImprovement)
class CapitalImprovementAdmin(admin.ModelAdmin):
    list_display = ["title", "ownership", "requested_amount", "approved_credit", "status"]
    list_filter = ["status", "category"]


@admin.register(OccupancyCheck)
class OccupancyCheckAdmin(admin.ModelAdmin):
    list_display = ["ownership", "year", "due_date", "result", "method"]
    list_filter = ["year", "result"]


@admin.register(RefinanceRequest)
class RefinanceRequestAdmin(admin.ModelAdmin):
    list_display = ["ownership", "lender", "loan_amount", "status", "created_at"]
    list_filter = ["status", "purpose"]


@admin.register(Appraisal)
class AppraisalAdmin(admin.ModelAdmin):
    list_display = ["home", "effective_date", "value", "purpose"]


@admin.register(Subsidy)
class SubsidyAdmin(admin.ModelAdmin):
    list_display = ["home", "source", "amount", "funded_on", "affordability_years"]
    list_filter = ["source", "kind"]
