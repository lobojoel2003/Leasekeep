from django.urls import path

from . import views

app_name = "formulas"
urlpatterns = [
    path("", views.formula_list, name="list"),
    path("new/", views.formula_create, name="create"),
    path("<int:pk>/", views.formula_detail, name="detail"),
    path("<int:pk>/edit/", views.formula_edit, name="edit"),
    path("indexes/new/", views.series_create, name="series_create"),
    path("indexes/<int:pk>/", views.series_detail, name="series"),
]
