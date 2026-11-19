from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from leasekeep.billing.services import build_ledger
from leasekeep.core.auth import staff_required
from leasekeep.core.notify import notify_household
from leasekeep.formulas.engine import money
from leasekeep.reports.metrics import portfolio_valuation

from . import forms, services
from .models import (
    CapitalImprovement,
    GroundLease,
    Home,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
)
from .timeline import build_events, group_by_year

# ---------------------------------------------------------------------------
# Homes
# ---------------------------------------------------------------------------


@staff_required
def home_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    homes = Home.objects.all().prefetch_related("ownerships__household", "ownerships__formula")
    if q:
        homes = homes.filter(
            Q(address_line1__icontains=q)
            | Q(address_line2__icontains=q)
            | Q(city__icontains=q)
            | Q(parcel_id__icontains=q)
            | Q(ownerships__household__name__icontains=q)
            | Q(ownerships__lease__lease_number__icontains=q)
        ).distinct()
    if status == "occupied":
        homes = homes.filter(ownerships__status=Ownership.Status.ACTIVE).distinct()
    elif status == "vacant":
        homes = homes.exclude(ownerships__status=Ownership.Status.ACTIVE)

    quotes = {q.ownership.home_id: q for q in portfolio_valuation().quotes}
    rows = [(home, quotes.get(home.pk)) for home in homes]
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "homes/home_list.html",
        {"page": page, "q": q, "status": status, "total": len(rows)},
    )


@staff_required
def home_create(request):
    form = forms.HomeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        home = form.save()
        messages.success(request, f"{home} added to the portfolio.")
        return redirect(home)
    return render(
        request, "homes/form.html", {"form": form, "title": "Add a home", "back": reverse("homes:list")}
    )


@staff_required
def home_edit(request, pk):
    home = get_object_or_404(Home, pk=pk)
    form = forms.HomeForm(request.POST or None, instance=home)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Home details saved.")
        return redirect(home)
    return render(
        request, "homes/form.html", {"form": form, "title": f"Edit {home}", "back": home.get_absolute_url()}
    )


@staff_required
def home_detail(request, pk):
    home = get_object_or_404(Home, pk=pk)
    ownership = home.current_ownership
    newest_first = request.GET.get("order") == "newest"
    events = build_events(home)
    pq = services.quote(ownership) if ownership else None
    lease = ownership.lease_or_none if ownership else None
    ledger = build_ledger(lease) if lease else None
    return render(
        request,
        "homes/home_detail.html",
        {
            "home": home,
            "ownership": ownership,
            "quote": pq,
            "lease": lease,
            "ledger": ledger,
            "years": group_by_year(events, newest_first=newest_first),
            "newest_first": newest_first,
            "past_ownerships": home.ownerships.exclude(status=Ownership.Status.ACTIVE).select_related(
                "household"
            ),
            "subsidies": home.subsidies.all(),
            "appraisals": home.appraisals.all()[:6],
            "open_checks": ownership.occupancy_checks.filter(
                result__in=[OccupancyCheck.Result.PENDING, OccupancyCheck.Result.SUBMITTED]
            )
            if ownership
            else [],
        },
    )


@staff_required
def ownership_create(request, pk):
    home = get_object_or_404(Home, pk=pk)
    form = forms.OwnershipForm(request.POST or None, request.FILES or None, home=home)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            ownership = form.save(commit=False)
            ownership.home = home
            ownership.save()
            GroundLease.objects.create(
                ownership=ownership,
                lease_number=form.cleaned_data["lease_number"],
                start_date=ownership.purchase_date,
                term_years=form.cleaned_data["term_years"],
                monthly_fee=form.cleaned_data["monthly_fee"],
                recording_reference=form.cleaned_data["recording_reference"],
                document=form.cleaned_data.get("lease_document") or "",
            )
        messages.success(request, f"{ownership.household} is now the homeowner of record.")
        return redirect(home)
    return render(
        request,
        "homes/form.html",
        {
            "form": form,
            "title": f"Record a sale: {home}",
            "intro": "Use this when a household buys the home and signs a ground lease. "
            "For a later sale by that household, use Record resale instead.",
            "back": home.get_absolute_url(),
            "multipart": True,
        },
    )


@staff_required
def appraisal_create(request, pk):
    home = get_object_or_404(Home, pk=pk)
    form = forms.AppraisalForm(request.POST or None, initial={"effective_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        appraisal = form.save(commit=False)
        appraisal.home = home
        appraisal.save()
        messages.success(request, f"Appraisal of {money(appraisal.value)} recorded.")
        return redirect(home)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": f"Record an appraisal: {home}", "back": home.get_absolute_url()},
    )


@staff_required
def subsidy_create(request, pk):
    home = get_object_or_404(Home, pk=pk)
    form = forms.SubsidyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        subsidy = form.save(commit=False)
        subsidy.home = home
        subsidy.save()
        messages.success(request, "Subsidy recorded.")
        return redirect(home)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": f"Record a subsidy: {home}", "back": home.get_absolute_url()},
    )


# ---------------------------------------------------------------------------
# Formula price and resale
# ---------------------------------------------------------------------------


@staff_required
def formula_price(request, pk):
    ownership = get_object_or_404(
        Ownership.objects.select_related("home", "household", "formula__index_series"), pk=pk
    )
    form = forms.WhatIfForm(request.GET or None)
    overrides = {}
    on = None
    if form.is_valid():
        on = form.cleaned_data.get("on")
        if form.cleaned_data.get("appraised_value"):
            overrides["appraised_value"] = form.cleaned_data["appraised_value"]
        if form.cleaned_data.get("index_value"):
            overrides["index_value"] = form.cleaned_data["index_value"]
    pq = services.quote(ownership, on, **overrides)
    on_file = services.quote(ownership) if (overrides or on) else pq
    return render(
        request,
        "homes/formula_price.html",
        {"ownership": ownership, "home": ownership.home, "quote": pq, "on_file": on_file, "form": form},
    )


@staff_required
def resale(request, pk):
    ownership = get_object_or_404(Ownership.objects.select_related("home", "household", "formula"), pk=pk)
    if not ownership.is_active:
        messages.error(request, "This ownership has already ended.")
        return redirect(ownership.home)
    pq = services.quote(ownership)
    form = forms.ResaleForm(request.POST or None, ownership=ownership)
    if request.method == "GET" and pq.price:
        form.fields["sale_price"].initial = pq.price
        if pq.market_value:
            form.fields["appraised_value"].initial = pq.market_value
    if request.method == "POST" and form.is_valid():
        try:
            result = services.record_resale(ownership, **form.cleaned_data)
        except services.ResaleError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                f"Resale recorded. {result.new_ownership.household} now holds lease "
                f"{result.new_lease.lease_number}.",
            )
            return redirect(ownership.home)
    return render(request, "homes/resale.html", {"ownership": ownership, "quote": pq, "form": form})


# ---------------------------------------------------------------------------
# Capital improvements
# ---------------------------------------------------------------------------


@staff_required
def improvement_list(request):
    status = request.GET.get("status", CapitalImprovement.Status.REQUESTED)
    items = CapitalImprovement.objects.select_related("ownership__home", "ownership__household")
    if status != "all":
        items = items.filter(status=status)
    counts = dict(CapitalImprovement.objects.values_list("status").annotate(n=Count("pk")))
    return render(
        request,
        "homes/improvement_list.html",
        {
            "items": items[:200],
            "status": status,
            "counts": counts,
            "statuses": CapitalImprovement.Status.choices,
        },
    )


@staff_required
def improvement_create(request, pk):
    ownership = get_object_or_404(Ownership, pk=pk, status=Ownership.Status.ACTIVE)
    form = forms.ImprovementForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.ownership = ownership
        item.save()
        messages.success(request, "Improvement added. Review it to approve a credit.")
        return redirect(item)
    return render(
        request,
        "homes/form.html",
        {
            "form": form,
            "title": f"Add an improvement: {ownership.home}",
            "back": ownership.home.get_absolute_url(),
            "multipart": True,
        },
    )


@staff_required
def improvement_review(request, pk):
    item = get_object_or_404(
        CapitalImprovement.objects.select_related("ownership__home", "ownership__household"), pk=pk
    )
    form = forms.ImprovementDecisionForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        decision = form.cleaned_data["decision"]
        changed = decision != item.status or decision == CapitalImprovement.Status.APPROVED
        item.status = decision
        if decision in (CapitalImprovement.Status.APPROVED, CapitalImprovement.Status.DENIED):
            item.decided_on = timezone.localdate()
            item.decided_by = request.user
        item.save()
        if changed and decision != CapitalImprovement.Status.REQUESTED:
            notify_household(
                item.ownership.household,
                f"Your improvement credit request was {item.get_status_display().lower()}",
                f"{item.title}: {item.get_status_display()}."
                + (
                    f" Credit: {money(item.approved_credit)}."
                    if item.approved_credit and decision == "approved"
                    else ""
                )
                + (f"\n\n{item.decision_notes}" if item.decision_notes else ""),
            )
        messages.success(request, f"“{item.title}” marked {item.get_status_display().lower()}.")
        return redirect("homes:improvements")
    pq = services.quote(item.ownership)
    return render(request, "homes/improvement_review.html", {"item": item, "form": form, "quote": pq})


# ---------------------------------------------------------------------------
# Occupancy checks
# ---------------------------------------------------------------------------


@staff_required
def occupancy_list(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
    except ValueError:
        year = today.year
    checks = (
        OccupancyCheck.objects.filter(year=year)
        .select_related("ownership__home", "ownership__household")
        .order_by("result", "ownership__home__address_line1")
    )
    result = request.GET.get("result", "")
    if result:
        checks = checks.filter(result=result)
    summary = dict(OccupancyCheck.objects.filter(year=year).values_list("result").annotate(n=Count("pk")))
    eligible = Ownership.objects.filter(
        status=Ownership.Status.ACTIVE, purchase_date__lt=f"{year}-01-01"
    ).count()
    years = sorted(set(OccupancyCheck.objects.values_list("year", flat=True)) | {today.year}, reverse=True)
    return render(
        request,
        "homes/occupancy_list.html",
        {
            "checks": checks,
            "year": year,
            "years": years,
            "summary": summary,
            "total": sum(summary.values()),
            "eligible": eligible,
            "result": result,
            "results": OccupancyCheck.Result.choices,
            "today": today,
        },
    )


@staff_required
@require_POST
def occupancy_schedule(request):
    try:
        year = int(request.POST.get("year", ""))
    except ValueError:
        messages.error(request, "Choose a year to schedule.")
        return redirect("homes:occupancy")
    created = services.schedule_occupancy_checks(year)
    if created:
        messages.success(
            request, f"Scheduled {created} occupancy check{'s' if created != 1 else ''} for {year}."
        )
    else:
        messages.info(request, f"Every eligible home already has a {year} check.")
    return redirect(f"{reverse('homes:occupancy')}?year={year}")


@staff_required
def occupancy_record(request, pk):
    check = get_object_or_404(
        OccupancyCheck.objects.select_related("ownership__home", "ownership__household"), pk=pk
    )
    form = forms.OccupancyRecordForm(request.POST or None, instance=check)
    if request.method == "POST" and form.is_valid():
        check = form.save(commit=False)
        check.reviewed_by = request.user
        check.save()
        messages.success(request, f"{check.year} check for {check.ownership.home} saved.")
        return redirect(f"{reverse('homes:occupancy')}?year={check.year}")
    history = check.ownership.occupancy_checks.exclude(pk=check.pk).order_by("-year")
    return render(request, "homes/occupancy_record.html", {"check": check, "form": form, "history": history})


# ---------------------------------------------------------------------------
# Refinance approvals
# ---------------------------------------------------------------------------


@staff_required
def refinance_list(request):
    show = request.GET.get("show", "open")
    items = RefinanceRequest.objects.select_related("ownership__home", "ownership__household")
    if show == "open":
        items = items.filter(status__in=RefinanceRequest.OPEN_STATUSES)
    return render(request, "homes/refinance_list.html", {"items": items[:200], "show": show})


@staff_required
def refinance_create(request, pk):
    ownership = get_object_or_404(Ownership, pk=pk, status=Ownership.Status.ACTIVE)
    form = forms.RefinanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        refi = form.save(commit=False)
        refi.ownership = ownership
        refi.save()
        services.evaluate_refinance(refi)
        messages.success(request, "Refinance request added.")
        return redirect(refi)
    return render(
        request,
        "homes/form.html",
        {
            "form": form,
            "title": f"Refinance request: {ownership.home}",
            "back": ownership.home.get_absolute_url(),
        },
    )


@staff_required
def refinance_review(request, pk):
    refi = get_object_or_404(
        RefinanceRequest.objects.select_related(
            "ownership__home", "ownership__household", "ownership__formula"
        ),
        pk=pk,
    )
    pq = services.evaluate_refinance(refi, save=refi.is_open)
    form = forms.RefinanceDecisionForm(request.POST or None, instance=refi)
    if request.method == "POST" and form.is_valid():
        refi = form.save(commit=False)
        if refi.status not in RefinanceRequest.OPEN_STATUSES:
            refi.decided_on = timezone.localdate()
            refi.decided_by = request.user
        refi.save()
        if refi.status not in RefinanceRequest.OPEN_STATUSES:
            notify_household(
                refi.ownership.household,
                f"Your refinance request: {refi.get_status_display()}",
                f"Lender: {refi.lender}\nLoan amount: {money(refi.loan_amount)}\n"
                f"Decision: {refi.get_status_display()}\n\n{refi.conditions}",
            )
        messages.success(request, f"Refinance request marked {refi.get_status_display().lower()}.")
        return redirect("homes:refinances")
    return render(request, "homes/refinance_review.html", {"refi": refi, "quote": pq, "form": form})


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


@staff_required
def household_list(request):
    q = request.GET.get("q", "").strip()
    households = (
        Household.objects.annotate(n_homes=Count("ownerships")).select_related("portal_user").order_by("name")
    )
    if q:
        households = households.filter(
            Q(name__icontains=q)
            | Q(primary_contact__icontains=q)
            | Q(co_owners__icontains=q)
            | Q(email__icontains=q)
        )
    page = Paginator(households, 50).get_page(request.GET.get("page"))
    return render(request, "homes/household_list.html", {"page": page, "q": q})


@staff_required
def household_create(request):
    form = forms.HouseholdForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        household = form.save()
        messages.success(request, f"{household} added.")
        nxt = request.GET.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(household)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": "Add a household", "back": reverse("homes:households")},
    )


@staff_required
def household_edit(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = forms.HouseholdForm(request.POST or None, instance=household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Household saved.")
        return redirect(household)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": f"Edit {household}", "back": household.get_absolute_url()},
    )


@staff_required
def household_detail(request, pk):
    household = get_object_or_404(Household.objects.select_related("portal_user"), pk=pk)
    ownerships = household.ownerships.select_related("home", "formula").order_by("-purchase_date")
    return render(
        request,
        "homes/household_detail.html",
        {
            "household": household,
            "ownerships": ownerships,
            "invite_form": forms.PortalInviteForm(household=household),
        },
    )


@staff_required
@require_POST
def household_invite(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = forms.PortalInviteForm(request.POST, household=household)
    if not form.is_valid():
        for error in form.errors.get("email", []):
            messages.error(request, error)
        return redirect(household)
    email = form.cleaned_data["email"]
    user_model = get_user_model()
    with transaction.atomic():
        user = household.portal_user or user_model.objects.filter(email__iexact=email).first()
        if user is None:
            user = user_model.objects.create_user(username=email, email=email)
            user.set_unusable_password()
            user.save()
        elif user.email.lower() != email:
            user.email = email
            user.save(update_fields=["email"])
        household.portal_user = user
        household.save(update_fields=["portal_user"])
    reset = forms.PortalInviteResetForm({"email": email})
    if reset.is_valid():
        reset.save(
            request=request,
            use_https=request.is_secure(),
            subject_template_name="registration/portal_invite_subject.txt",
            email_template_name="registration/portal_invite_email.txt",
            extra_email_context={"household": household},
        )
    messages.success(request, f"Portal invitation sent to {email}.")
    return redirect(household)
