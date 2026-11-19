from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from leasekeep.billing.services import generate_charges, months_in_range


def parse_month(value: str) -> date:
    try:
        year, month = value.split("-")[:2]
        return date(int(year), int(month), 1)
    except (ValueError, TypeError) as exc:
        raise CommandError(f"Months look like 2026-11, not {value!r}.") from exc


class Command(BaseCommand):
    help = "Create monthly ground lease fee charges for active leases (safe to run repeatedly)."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="Month to bill, YYYY-MM. Defaults to the current month.")
        parser.add_argument(
            "--from", dest="start", help="Backfill from this month (YYYY-MM) through --month."
        )

    def handle(self, *args, month=None, start=None, **options):
        end = parse_month(month) if month else timezone.localdate().replace(day=1)
        first = parse_month(start) if start else end
        if first > end:
            raise CommandError("--from must be on or before --month.")
        created = generate_charges(months_in_range(first, end))
        span = f"{first:%B %Y}" if first == end else f"{first:%B %Y} – {end:%B %Y}"
        self.stdout.write(self.style.SUCCESS(f"Created {created} lease fee charge(s) for {span}."))
