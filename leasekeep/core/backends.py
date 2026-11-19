from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Sign in with either a username (staff) or an email address (homeowners)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        user_model = get_user_model()
        user = user_model._default_manager.filter(username__iexact=username).first()
        if user is None and "@" in username:
            matches = list(user_model._default_manager.filter(email__iexact=username)[:2])
            user = matches[0] if len(matches) == 1 else None
        if user is None:
            user_model().set_password(password)  # equalize timing with a real check
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
