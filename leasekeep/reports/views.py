from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from leasekeep.core.auth import staff_required
from leasekeep.homes.models import Subsidy

from . import exports, metrics


def _csv_response(filename: str, header, rows) -> HttpResponse:
    response = HttpResponse(exports.to_csv(header, rows), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _date(value: str, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@staff_required
def index(request):
    today = timezone.localdate()
    fy = metrics.current_fiscal_year(today)
    return render(
        request,
        "reports/index.html",
        {
            "fiscal_year": fy,
            "years": list(range(fy, fy - 6, -1)),
            "today": today,
            "year_start": date(today.year, 1, 1),
            "home_assisted": Subsidy.objects.filter(source=Subsidy.Source.HOME)
            .values("home")
            .distinct()
            .count(),
        },
    )


@staff_required
def board(request):
    today = timezone.localdate()
    try:
        fy = int(request.GET.get("fy", metrics.current_fiscal_year(today)))
    except ValueError:
        fy = metrics.current_fiscal_year(today)
    report = metrics.board_report(fy)
    if request.GET.get("format") == "csv":
        return _csv_response(
            f"leasekeep-board-report-FY{fy}.csv",
            ["Measure", "Value", "Notes"],
            exports.board_report_rows(report),
        )
    return render(request, "reports/board.html", {"report": report, "today": today})


@staff_required
def home_compliance(request):
    on = _date(request.GET.get("on"), timezone.localdate())
    rows = exports.home_compliance_rows(on)
    if request.GET.get("format") == "html":
        return render(
            request, "reports/home_compliance.html", {"header": exports.HOME_HEADER, "rows": rows, "on": on}
        )
    return _csv_response(f"leasekeep-hud-home-compliance-{on.isoformat()}.csv", exports.HOME_HEADER, rows)


@staff_required
def valuation(request):
    on = _date(request.GET.get("on"), timezone.localdate())
    return _csv_response(
        f"leasekeep-portfolio-valuation-{on.isoformat()}.csv",
        exports.VALUATION_HEADER,
        exports.valuation_rows(on),
    )


@staff_required
def aging(request):
    on = _date(request.GET.get("on"), timezone.localdate())
    return _csv_response(
        f"leasekeep-lease-fee-aging-{on.isoformat()}.csv", exports.AGING_HEADER, exports.aging_rows(on)
    )


@staff_required
def payments(request):
    today = timezone.localdate()
    start = _date(request.GET.get("start"), date(today.year, 1, 1))
    end = _date(request.GET.get("end"), today)
    return _csv_response(
        f"leasekeep-payments-{start.isoformat()}-to-{end.isoformat()}.csv",
        exports.PAYMENTS_HEADER,
        exports.payment_rows(start, end),
    )
