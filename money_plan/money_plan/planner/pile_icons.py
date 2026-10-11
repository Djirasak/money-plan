"""The icons a pile can wear (lucide names; the SVGs live in templates/icons/)."""

from django.utils.translation import gettext_noop

from . import engine

PILE_ICONS = [
    ("wallet", gettext_noop("Wallet")),
    ("piggy-bank", gettext_noop("Piggy bank")),
    ("coins", gettext_noop("Coins")),
    ("banknote", gettext_noop("Banknote")),
    ("landmark", gettext_noop("Bank")),
    ("shopping-cart", gettext_noop("Shopping")),
    ("house", gettext_noop("Home")),
    ("car", gettext_noop("Car")),
    ("bus", gettext_noop("Transport")),
    ("utensils", gettext_noop("Food")),
    ("coffee", gettext_noop("Coffee")),
    ("heart-pulse", gettext_noop("Health")),
    ("graduation-cap", gettext_noop("Education")),
    ("plane", gettext_noop("Travel")),
    ("gift", gettext_noop("Gifts")),
    ("gamepad-2", gettext_noop("Games")),
    ("shirt", gettext_noop("Clothes")),
    ("smartphone", gettext_noop("Phone")),
    ("zap", gettext_noop("Utilities")),
    ("baby", gettext_noop("Family")),
    ("paw-print", gettext_noop("Pets")),
    ("briefcase", gettext_noop("Work")),
    ("trending-up", gettext_noop("Investing")),
    ("umbrella", gettext_noop("Insurance")),
    ("gem", gettext_noop("Treats")),
    ("dumbbell", gettext_noop("Fitness")),
    ("sparkles", gettext_noop("Fun")),
    ("shield-check", gettext_noop("Safety")),
]
PILE_ICON_KEYS = {key for key, _label in PILE_ICONS}
DEFAULT_ICONS = {engine.BUDGET: "wallet", engine.FUND: "piggy-bank"}
