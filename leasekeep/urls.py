from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from leasekeep.billing.views import stripe_webhook
from leasekeep.core import views as core

urlpatterns = [
    path("", core.home, name="home"),
    path("healthz", core.healthz, name="healthz"),
    path("accounts/login/", core.LoginView.as_view(), name="login"),
    path("accounts/logout/", core.logout_view, name="logout"),
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("", include("leasekeep.core.urls")),
    path("", include("leasekeep.homes.urls")),
    path("fees/", include("leasekeep.billing.urls")),
    path("formulas/", include("leasekeep.formulas.urls")),
    path("reports/", include("leasekeep.reports.urls")),
    path("portal/", include("leasekeep.portal.urls")),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "leasekeep.core.errors.forbidden"
handler404 = "leasekeep.core.errors.not_found"
handler500 = "leasekeep.core.errors.server_error"
