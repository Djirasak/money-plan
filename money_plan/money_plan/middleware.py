"""Thai first: the language comes from the visitor's choice, not from their browser."""

from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation


class ThaiFirstLocaleMiddleware(LocaleMiddleware):
    """Django's LocaleMiddleware trusts the browser's Accept-Language, so a phone set to
    English would see the whole app in English. Here the language is the one chosen with
    the language button (a cookie), otherwise ``settings.LANGUAGE_CODE`` (Thai)."""

    def process_request(self, request):
        chosen = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        language = (
            chosen if chosen in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE
        )
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
