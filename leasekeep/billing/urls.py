from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path("", views.fee_overview, name="overview"),
    path("generate/", views.generate, name="generate"),
    path("leases/<int:pk>/", views.ledger, name="ledger"),
    path("leases/<int:pk>/payments/new/", views.payment_create, name="payment_create"),
    path("leases/<int:pk>/charges/new/", views.charge_create, name="charge_create"),
    path("charges/<int:pk>/waive/", views.charge_waive, name="charge_waive"),
]
