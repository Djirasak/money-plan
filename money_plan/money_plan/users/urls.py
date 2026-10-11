from django.urls import path

from .views import EmailChangeView
from .views import NameChangeView
from .views import PasswordChangeView
from .views import PhotoChangeView
from .views import PhotoRemoveView
from .views import PhotoView
from .views import UsernameChangeView
from .views import user_detail_view

app_name = "users"
urlpatterns = [
    path(
        "<int:pk>/username/",
        view=UsernameChangeView.as_view(),
        name="change_username",
    ),
    path("<int:pk>/name/", view=NameChangeView.as_view(), name="change_name"),
    path("<int:pk>/email/", view=EmailChangeView.as_view(), name="change_email"),
    path(
        "<int:pk>/password/",
        view=PasswordChangeView.as_view(),
        name="change_password",
    ),
    path("<int:pk>/photo/", view=PhotoView.as_view(), name="photo"),
    path("<int:pk>/photo/change/", view=PhotoChangeView.as_view(), name="change_photo"),
    path("<int:pk>/photo/remove/", view=PhotoRemoveView.as_view(), name="remove_photo"),
    path("<int:pk>/", view=user_detail_view, name="detail"),
]
