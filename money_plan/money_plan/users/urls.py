from django.urls import path

from .views import EmailChangeView
from .views import NameChangeView
from .views import PasswordChangeView
from .views import PhotoChangeView
from .views import PhotoRemoveView
from .views import PhotoView
from .views import UsernameChangeView
from .views import user_detail_view
from .views import user_redirect_view
from .views import user_update_view

app_name = "users"
urlpatterns = [
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path("~username/", view=UsernameChangeView.as_view(), name="change_username"),
    path("~name/", view=NameChangeView.as_view(), name="change_name"),
    path("~email/", view=EmailChangeView.as_view(), name="change_email"),
    path("~password/", view=PasswordChangeView.as_view(), name="change_password"),
    path("~photo/", view=PhotoView.as_view(), name="photo"),
    path("~photo/change/", view=PhotoChangeView.as_view(), name="change_photo"),
    path("~photo/remove/", view=PhotoRemoveView.as_view(), name="remove_photo"),
    path("<str:username>/", view=user_detail_view, name="detail"),
]
