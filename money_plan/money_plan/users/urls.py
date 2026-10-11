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
    path("me/username/", view=UsernameChangeView.as_view(), name="change_username"),
    path("me/name/", view=NameChangeView.as_view(), name="change_name"),
    path("me/email/", view=EmailChangeView.as_view(), name="change_email"),
    path("me/password/", view=PasswordChangeView.as_view(), name="change_password"),
    path("me/photo/", view=PhotoView.as_view(), name="photo"),
    path("me/photo/change/", view=PhotoChangeView.as_view(), name="change_photo"),
    path("me/photo/remove/", view=PhotoRemoveView.as_view(), name="remove_photo"),
    path("<int:pk>/", view=user_detail_view, name="detail"),
]
