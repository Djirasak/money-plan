from django.urls import path

from . import views

app_name = "planner"
urlpatterns = [
    path("", views.SummaryView.as_view(), name="summary"),
    path("summary/content/", views.SummaryContentView.as_view(), name="summary_content"),
    path("log/", views.LogView.as_view(), name="log"),
    path("log/<int:pk>/edit/", views.LogView.as_view(), name="log_edit"),
    path("log/<int:pk>/delete/", views.LogDeleteView.as_view(), name="log_delete"),
    path("settings/", views.SettingsGeneralView.as_view(), name="settings"),
    path("settings/piles/", views.SettingsPilesView.as_view(), name="piles"),
    path("settings/plan/", views.SettingsPlanView.as_view(), name="plan"),
]
