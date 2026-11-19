from functools import cached_property

from django.conf import settings

from leasekeep.version import get_build_info

from .models import Organization


class NavCounts:
    """Badge counts for the staff sidebar, computed only if a template asks."""

    @cached_property
    def improvements(self) -> int:
        from leasekeep.homes.models import CapitalImprovement

        return CapitalImprovement.objects.filter(status=CapitalImprovement.Status.REQUESTED).count()

    @cached_property
    def refinances(self) -> int:
        from leasekeep.homes.models import RefinanceRequest

        return RefinanceRequest.objects.filter(status__in=RefinanceRequest.OPEN_STATUSES).count()

    @cached_property
    def occupancy(self) -> int:
        from leasekeep.homes.models import OccupancyCheck

        return OccupancyCheck.objects.filter(result=OccupancyCheck.Result.SUBMITTED).count()


def leasekeep(request):
    """Organization, build info and the signed-in user's role for every template."""
    user = getattr(request, "user", None)
    household = None
    is_staff = bool(user is not None and user.is_authenticated and user.is_staff)
    if user is not None and user.is_authenticated:
        household = getattr(user, "household", None)
    return {
        "organization": Organization.current(),
        "build": get_build_info(),
        "online_payments_enabled": bool(settings.STRIPE_SECRET_KEY),
        "is_staff_user": is_staff,
        "portal_household": household,
        "nav_counts": NavCounts() if is_staff else None,
    }
