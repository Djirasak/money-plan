from .base import *  # noqa: F403
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import RESEND_API_KEY
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="DoFNS4nrfu1CLS40cavAPTRy6i1PMFO79JWsOI8DCRcQebBr3roJAtsJ9qUR7mJU",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1", "mpa-dev.zercoms.com"]  # noqa: S104

# Behind the Cloudflare Tunnel: the browser talks HTTPS to the tunnel host, Django sees HTTP.
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-trusted-origins
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["https://mpa-dev.zercoms.com"],
)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
# Real sending through Resend when RESEND_API_KEY is set (.envs/.local/.email), else print to the console.
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default=(
        "anymail.backends.resend.EmailBackend"
        if RESEND_API_KEY
        else "django.core.mail.backends.console.EmailBackend"
    ),
)

# WhiteNoise
# ------------------------------------------------------------------------------
# http://whitenoise.evans.io/en/latest/django.html#using-whitenoise-in-development
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]
# runserver_nostatic hands static files to WhiteNoise, which only reads the app's static
# dirs when DEBUG is on. Force it so the CSS still loads with DEBUG = False (to try the
# real 404/500 pages) without running collectstatic.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True


# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
INSTALLED_APPS += ["debug_toolbar"]
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
# Hidden by default; set DJANGO_DEBUG_TOOLBAR=True in .envs/.local/.django to show it.
SHOW_DEBUG_TOOLBAR = env.bool("DJANGO_DEBUG_TOOLBAR", default=False)
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: SHOW_DEBUG_TOOLBAR,
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        # Disable profiling panel due to an issue with Python 3.12+:
        # https://github.com/jazzband/django-debug-toolbar/issues/1875
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
if env("USE_DOCKER") == "yes":
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS += [".".join([*ip.split(".")[:-1], "1"]) for ip in ips]
    try:
        _, _, ips = socket.gethostbyname_ex("node")
        INTERNAL_IPS.extend(ips)
    except socket.gaierror:
        # The node container isn't started (yet?)
        pass

# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]
# Celery
# ------------------------------------------------------------------------------

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-eager-propagates
CELERY_TASK_EAGER_PROPAGATES = True
# Your stuff...
# ------------------------------------------------------------------------------
