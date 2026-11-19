from django.urls import path

from . import views

app_name = "portal"
urlpatterns = [
    path("", views.home, name="home"),
    path("resale-value/", views.resale_value, name="resale_value"),
    path("payments/", views.payments, name="payments"),
    path("pay/", views.pay, name="pay"),
    path("pay/done/", views.pay_done, name="pay_done"),
    path("improvements/new/", views.improvement_new, name="improvement_new"),
    path("occupancy/<int:pk>/certify/", views.certify, name="certify"),
    path("refinance/new/", views.refinance_new, name="refinance_new"),
]
