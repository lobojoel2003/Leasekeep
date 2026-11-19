from django.core.management.base import BaseCommand
from django.utils import timezone

from leasekeep.homes.services import schedule_occupancy_checks


class Command(BaseCommand):
    help = "Create this year's owner-occupancy checks for every active ownership (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None)

    def handle(self, *args, year=None, **options):
        year = year or timezone.localdate().year
        created = schedule_occupancy_checks(year)
        self.stdout.write(self.style.SUCCESS(f"Scheduled {created} occupancy check(s) for {year}."))
