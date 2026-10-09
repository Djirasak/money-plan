from django.urls import path

from . import views

app_name = "planner"
urlpatterns = [
    path("", views.summary, name="summary"),
    path("log/", views.log, name="log"),
    path("log/<int:pk>/edit/", views.log, name="log_edit"),
    path("log/<int:pk>/delete/", views.log_delete, name="log_delete"),
    path("settings/", views.settings_general, name="settings"),
    path("settings/piles/", views.settings_piles, name="piles"),
    path("settings/plan/", views.settings_plan, name="plan"),
]
