"""Access control: staff screens and the homeowner portal are kept apart."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def staff_required(view):
    """Only CLT staff (``is_staff``) may use the stewardship screens."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            if getattr(request.user, "household", None) is not None:
                return redirect("portal:home")
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def owner_required(view):
    """Only a user linked to a household may use the owner portal."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        household = getattr(request.user, "household", None)
        if household is None:
            if request.user.is_staff:
                return redirect("core:dashboard")
            raise PermissionDenied
        request.household = household
        return view(request, *args, **kwargs)

    return wrapper
