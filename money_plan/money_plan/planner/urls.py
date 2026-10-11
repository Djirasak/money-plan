from django.urls import path

from . import views
from . import views_share

app_name = "planner"
urlpatterns = [
    path("", views.SummaryView.as_view(), name="summary"),
    path(
        "summary/content/",
        views.SummaryContentView.as_view(),
        name="summary_content",
    ),
    path("log/", views.LogView.as_view(), name="log"),
    path("log/<int:pk>/edit/", views.LogView.as_view(), name="log_edit"),
    path("log/<int:pk>/delete/", views.LogDeleteView.as_view(), name="log_delete"),
    path("settings/", views.SettingsGeneralView.as_view(), name="settings"),
    path("settings/salary/", views.SettingsSalaryView.as_view(), name="salary"),
    path("settings/piles/", views.SettingsPilesView.as_view(), name="piles"),
    path(
        "settings/piles/reorder/",
        views.PileReorderView.as_view(),
        name="piles_reorder",
    ),
    path("settings/plan/", views.SettingsPlanView.as_view(), name="plan"),
    path("settings/share/", views_share.SettingsShareView.as_view(), name="share"),
    path(
        "settings/share/export/",
        views_share.ExportView.as_view(),
        name="share_export",
    ),
    path("import/", views_share.TemplateImportView.as_view(), name="import_file"),
    path("t/<str:token>/", views_share.TemplateImportView.as_view(), name="template"),
]
