from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from leasekeep.formulas.engine import money
from leasekeep.homes.models import CapitalImprovement, OccupancyCheck, RefinanceRequest
from leasekeep.reports import metrics
from leasekeep.version import get_build_info

from .auth import staff_required
from .charts import grouped_columns


def home(request):
    """Send each person to the right place: staff to the dashboard, owners to the portal."""
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.is_staff:
        return redirect("core:dashboard")
    if getattr(request.user, "household", None) is not None:
        return redirect("portal:home")
    return render(request, "core/no_role.html", status=403)


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


def logout_view(request):
    from django.contrib.auth import logout

    if request.method == "POST":
        logout(request)
        messages.info(request, "You're signed out.")
    return redirect("login")


@staff_required
def dashboard(request):
    today = timezone.localdate()
    data = metrics.dashboard(today)
    chart = grouped_columns(
        data.series,
        ["billed", "collected"],
        label_key="month",
        label_format=lambda d: d.strftime("%b"),
        tip_names={"billed": "billed", "collected": "collected"},
        money_format=money,
    )
    for group, row in zip(chart.groups, data.series, strict=True):
        group.tip = f"{row['month']:%B %Y}|" + group.tip.split("|", 1)[1]

    work = []
    for check in (
        OccupancyCheck.objects.filter(result=OccupancyCheck.Result.SUBMITTED)
        .select_related("ownership__home", "ownership__household")
        .order_by("due_date")[:5]
    ):
        work.append(("occupancy", "Review occupancy certification", check, check.ownership.home))
    for check in (
        OccupancyCheck.objects.filter(result=OccupancyCheck.Result.PENDING, due_date__lt=today)
        .select_related("ownership__home", "ownership__household")
        .order_by("due_date")[:5]
    ):
        work.append(("overdue", "Occupancy check overdue", check, check.ownership.home))
    for item in (
        CapitalImprovement.objects.filter(status=CapitalImprovement.Status.REQUESTED)
        .select_related("ownership__home")
        .order_by("created_at")[:5]
    ):
        work.append(("improvement", "Improvement credit request", item, item.ownership.home))
    for refi in (
        RefinanceRequest.objects.filter(status__in=RefinanceRequest.OPEN_STATUSES)
        .select_related("ownership__home")
        .order_by("created_at")[:5]
    ):
        work.append(("refinance", "Refinance approval request", refi, refi.ownership.home))

    late = [row for row in data.aging.rows if row.days_60 + row.days_90 > 0][:5]
    return render(
        request,
        "core/dashboard.html",
        {"data": data, "chart": chart, "work": work, "late": late, "today": today},
    )


@never_cache
@require_GET
def healthz(request):
    """Liveness/readiness probe with version and build metadata."""
    info = get_build_info().as_dict()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        info["database"] = "ok"
        status = 200
    except Exception:
        info["database"] = "unavailable"
        status = 503
    info["status"] = "ok" if status == 200 else "degraded"
    return JsonResponse(info, status=status)
