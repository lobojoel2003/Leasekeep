from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.index, name="index"),
    path("board/", views.board, name="board"),
    path("hud-home-compliance/", views.home_compliance, name="home_compliance"),
    path("portfolio-valuation.csv", views.valuation, name="valuation"),
    path("lease-fee-aging.csv", views.aging, name="aging"),
    path("payments.csv", views.payments, name="payments"),
]
