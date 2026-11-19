from django.urls import path

from . import views

app_name = "homes"
urlpatterns = [
    path("homes/", views.home_list, name="list"),
    path("homes/new/", views.home_create, name="create"),
    path("homes/<int:pk>/", views.home_detail, name="detail"),
    path("homes/<int:pk>/edit/", views.home_edit, name="edit"),
    path("homes/<int:pk>/sell/", views.ownership_create, name="ownership_create"),
    path("homes/<int:pk>/appraisals/new/", views.appraisal_create, name="appraisal_create"),
    path("homes/<int:pk>/subsidies/new/", views.subsidy_create, name="subsidy_create"),
    path("ownerships/<int:pk>/formula/", views.formula_price, name="formula"),
    path("ownerships/<int:pk>/resale/", views.resale, name="resale"),
    path("ownerships/<int:pk>/improvements/new/", views.improvement_create, name="improvement_create"),
    path("ownerships/<int:pk>/refinances/new/", views.refinance_create, name="refinance_create"),
    path("improvements/", views.improvement_list, name="improvements"),
    path("improvements/<int:pk>/", views.improvement_review, name="improvement_review"),
    path("occupancy/", views.occupancy_list, name="occupancy"),
    path("occupancy/schedule/", views.occupancy_schedule, name="occupancy_schedule"),
    path("occupancy/<int:pk>/", views.occupancy_record, name="occupancy_record"),
    path("refinances/", views.refinance_list, name="refinances"),
    path("refinances/<int:pk>/", views.refinance_review, name="refinance_review"),
    path("households/", views.household_list, name="households"),
    path("households/new/", views.household_create, name="household_create"),
    path("households/<int:pk>/", views.household_detail, name="household_detail"),
    path("households/<int:pk>/edit/", views.household_edit, name="household_edit"),
    path("households/<int:pk>/invite/", views.household_invite, name="household_invite"),
]
