from __future__ import annotations

import copy
import json
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from money_plan.planner import sharing
from money_plan.planner.models import LogEntry
from money_plan.planner.models import Pile
from money_plan.planner.models import PlanItem
from money_plan.planner.models import PlanPeriod
from money_plan.planner.models import Salary
from money_plan.planner.models import SharedTemplate
from money_plan.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

RESERVE = "เงินสำรอง"  # the seeded piles are named in the default language (Thai)
EXPENSES = "ค่าใช้จ่าย"


@pytest.fixture
def rich(client_in, user):
    """The seeded user, plus a fixed target, a salary goal and a conditional plan."""
    reserve = Pile.objects.get(user=user, name=RESERVE)
    reserve.target = Decimal(123456)
    reserve.save()
    trip = Pile.objects.create(
        user=user,
        name="Trip",
        target_percent=Decimal(30),
        target_months=4,
        cap=Decimal(98765),
        order=9,
    )
    cond = PlanPeriod.objects.create(
        user=user,
        effective_month="2027-03",
        name="After reserve",
        cond_pile=reserve,
        cond_op="gte",
        cond_amount=Decimal(777777),
    )
    for pile, pct in ((reserve, 10), (trip, 20)):
        PlanItem.objects.create(period=cond, pile=pile, percent=pct)
    LogEntry.objects.create(
        user=user,
        type=LogEntry.SPEND,
        from_pile=trip,
        amount=Decimal("4321.50"),
        note="secret note",
    )
    return user


def other_user_client(client_class):
    other = UserFactory()
    from money_plan.planner import services

    services.ensure_defaults(other)
    client = client_class()
    client.force_login(other)
    return other, client


class TestPayload:
    def test_no_money_leaks_into_the_template(self, rich):
        text = json.dumps(sharing.build_payload(rich), ensure_ascii=False)
        for secret in (
            "123456",
            "98765",
            "777777",
            "48000",
            "4321",
            "secret note",
            rich.username,
            rich.email,
        ):
            assert secret not in text
        data = sharing.build_payload(rich)
        reserve = next(p for p in data["piles"] if p["name"] == RESERVE)
        assert reserve["target"] == {"type": "fixed"}  # the amount is dropped
        trip = next(p for p in data["piles"] if p["name"] == "Trip")
        assert trip["has_cap"] is True
        assert trip["target"] == {"type": "salary", "percent": "30", "months": 4}

    def test_plans_keep_percentages_and_relative_start(self, rich):
        plans = sharing.build_payload(rich)["plans"]
        assert [p["offset"] for p in plans] == [0, plans[1]["offset"]]
        assert plans[1]["offset"] > 0
        assert plans[1]["condition"]["op"] == "gte"
        assert plans[1]["condition"]["use_target"] is False

    def test_icons_travel_with_the_template_and_unknown_ones_are_refused(self, rich):
        Pile.objects.filter(user=rich, name="Trip").update(icon="plane")
        payload = sharing.build_payload(rich)
        trip = next(p for p in payload["piles"] if p["name"] == "Trip")
        assert trip["icon"] == "plane"
        assert sharing.validate_payload(payload)
        trip["icon"] = "<script>"
        with pytest.raises(sharing.TemplateError):
            sharing.validate_payload(payload)

    def test_an_old_template_without_icons_still_imports_with_defaults(self, rich):
        payload = sharing.build_payload(rich)
        for pile in payload["piles"]:
            del pile["icon"]
        assert all(p["icon"] == "" for p in sharing.validate_payload(payload)["piles"])

    def test_a_built_payload_validates(self, rich):
        payload = sharing.build_payload(rich)
        assert sharing.validate_payload(payload)["piles"][0]["name"]


class TestValidation:
    def good(self, rich):
        return sharing.build_payload(rich)

    def bad(self, payload, message=None):
        with pytest.raises(sharing.TemplateError) as exc:
            sharing.validate_payload(payload)
        if message:
            assert message in str(exc.value)

    def test_rejects_non_templates(self):
        for junk in (
            None,
            [],
            "x",
            3,
            {},
            {"schema": 2, "piles": [], "plans": []},
            {"schema": 1, "piles": [], "plans": []},
        ):
            self.bad(junk)

    def test_unknown_fields_are_dropped_not_kept(self, rich):
        payload = self.good(rich)
        payload["evil"] = "<script>"
        payload["piles"][0]["user_id"] = 5
        clean = sharing.validate_payload(payload)
        assert "evil" not in clean
        assert "user_id" not in clean["piles"][0]

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p["piles"][0].update(name="=cmd|calc"),  # spreadsheet formula
            lambda p: p["piles"][0].update(name="x" * 25),
            lambda p: p["piles"][0].update(name="a\x00b"),
            lambda p: p["piles"][0].update(name=""),
            lambda p: p["piles"][0].update(color="red"),
            lambda p: p["piles"][0].update(color="#12345"),
            lambda p: p["piles"][0].update(kind="evil"),
            lambda p: p["piles"][0].update(mode=1),
            lambda p: p["piles"][0].update(key="BAD KEY"),
            lambda p: p["piles"][0].update(overflow_to=p["piles"][0]["key"]),
            lambda p: p["piles"][0].update(overflow_to="nope"),
            lambda p: p["piles"][0].update(
                target={"type": "salary", "percent": "abc", "months": 3},
            ),
            lambda p: p["piles"][0].update(
                target={"type": "salary", "percent": "10", "months": 0},
            ),
            lambda p: p["piles"][0].update(
                target={"type": "salary", "percent": "10", "months": True},
            ),
            lambda p: p["piles"][0].update(
                target={"type": "salary", "percent": "NaN", "months": 3},
            ),
            lambda p: p["piles"][0].update(target={"type": "nope"}),
            lambda p: p["plans"][0]["items"][0].update(percent="101"),
            lambda p: p["plans"][0]["items"][0].update(percent="-1"),
            lambda p: p["plans"][0]["items"][0].update(pile="nope"),
            lambda p: p["plans"][0].update(offset=-1),
            lambda p: p["plans"][0].update(offset=10**9),
            lambda p: p["plans"][0].update(name="x" * 61),
            lambda p: p["plans"][0].update(
                condition={"pile": "p1", "op": "evil", "use_target": False},
            ),
            lambda p: p["plans"][0].update(items="nope"),
        ],
    )
    def test_malicious_or_broken_fields_are_rejected(self, rich, mutate):
        payload = copy.deepcopy(self.good(rich))
        mutate(payload)
        self.bad(payload)

    def test_duplicate_names_and_keys_are_rejected(self, rich):
        payload = self.good(rich)
        payload["piles"][1]["name"] = payload["piles"][0]["name"]
        self.bad(payload)
        payload = self.good(rich)
        payload["piles"][1]["key"] = payload["piles"][0]["key"]
        self.bad(payload)

    def test_overflow_cycles_are_rejected(self, rich):
        payload = self.good(rich)
        a, b = payload["piles"][0], payload["piles"][1]
        a["overflow_to"], b["overflow_to"] = b["key"], a["key"]
        self.bad(payload)

    def test_a_condition_on_a_missing_goal_is_rejected(self, rich):
        payload = self.good(rich)
        no_goal = next(p for p in payload["piles"] if p["target"]["type"] == "none")
        payload["plans"][0]["condition"] = {
            "pile": no_goal["key"],
            "op": "gte",
            "use_target": True,
        }
        self.bad(payload)

    def test_size_limits(self, rich):
        payload = self.good(rich)
        payload["piles"] = [
            {
                **payload["piles"][0],
                "key": f"k{i}",
                "name": f"n{i}",
                "overflow_to": None,
            }
            for i in range(sharing.MAX_PILES + 1)
        ]
        self.bad(payload)
        payload = self.good(rich)
        payload["plans"] = payload["plans"] * (sharing.MAX_PLANS + 1)
        self.bad(payload)

    def test_meta_limits(self):
        assert sharing.validate_meta("  Hi ", "x") == ("Hi", "x")
        for title in ("", "   ", "x" * 81, None, "a\x00"):
            with pytest.raises(sharing.TemplateError):
                sharing.validate_meta(title, "")
        with pytest.raises(sharing.TemplateError):
            sharing.validate_meta("ok", "d" * 501)


class TestImport:
    def run(self, rich, payload=None, month="2027-06", **amounts):
        user = UserFactory()
        from money_plan.planner import services

        services.ensure_defaults(user)
        payload = sharing.validate_payload(payload or sharing.build_payload(rich))
        form = sharing.ImportForm(
            payload,
            {"month": month, **{k: str(v) for k, v in amounts.items()}},
        )
        assert form.is_valid(), form.errors
        return (
            user,
            payload,
            sharing.import_template(
                user,
                payload,
                month=month,
                amounts=form.cleaned_data,
            ),
        )

    def test_asks_for_the_amounts_a_template_leaves_out(self, rich):
        payload = sharing.validate_payload(sharing.build_payload(rich))
        names = set(sharing.ImportForm(payload).fields)
        assert {"month", "cap_p4", "target_p3", "cond_1"} <= names or any(
            n.startswith("target_") for n in names
        )
        assert any(n.startswith("cap_") for n in names)
        assert any(n.startswith("cond_") for n in names)

    def test_import_adds_piles_and_plans_without_touching_existing_data(self, rich):
        user = UserFactory()
        from money_plan.planner import services

        services.ensure_defaults(user)
        before = list(user.piles.values_list("name", flat=True))
        payload = sharing.validate_payload(sharing.build_payload(rich))
        amounts = {"month": "2027-06"}
        for name in sharing.ImportForm(payload).fields:
            if name != "month":
                amounts[name] = "1000"
        form = sharing.ImportForm(payload, amounts)
        assert form.is_valid(), form.errors
        result = sharing.import_template(
            user,
            payload,
            month="2027-06",
            amounts=form.cleaned_data,
        )
        assert result.piles == len(payload["piles"])
        names = list(user.piles.values_list("name", flat=True))
        assert all(name in names for name in before)  # nothing removed
        assert len(names) == len(set(names))  # name clashes were renamed
        assert f"{RESERVE} 2" in names
        trip = Pile.objects.get(user=user, name="Trip")
        assert (trip.cap, trip.target_percent, trip.target_months) == (
            Decimal(1000),
            Decimal(30),
            4,
        )
        reserve = Pile.objects.get(user=user, name=f"{RESERVE} 2")
        assert reserve.target == Decimal(1000)
        # overflow links point at the NEW piles, not the user's old ones
        assert Pile.objects.get(user=user, name=f"{EXPENSES} 2").overflow_to == reserve

    def test_plans_start_in_the_chosen_month_with_their_offsets(self, rich):
        user, _payload, _result = self.run(rich, **self._fill(rich))
        months = sorted(user.plan_periods.values_list("effective_month", flat=True))
        assert "2027-06" in months
        later = sharing.build_payload(rich)["plans"][1]["offset"]
        assert f"{2027 + (5 + later) // 12:04d}-{(5 + later) % 12 + 1:02d}" in months

    def test_every_new_plan_covers_every_pile(self, rich):
        user, _payload, _result = self.run(rich, **self._fill(rich))
        total_piles = user.piles.count()
        imported = user.plan_periods.filter(name="After reserve").get()
        assert imported.items.count() == total_piles
        assert imported.cond_pile.name.startswith(RESERVE)
        assert imported.cond_amount == Decimal(1000)

    def test_a_goal_condition_follows_the_new_piles_goal(self, rich):
        payload = sharing.build_payload(rich)
        payload["plans"][1]["condition"]["use_target"] = True
        user, _payload, _result = self.run(rich, payload, **self._fill(rich, payload))
        plan = user.plan_periods.get(name="After reserve")
        assert plan.cond_use_target is True
        assert plan.cond_amount == plan.cond_pile.target

    def test_too_many_piles_is_refused_and_rolls_back(self, rich, user):
        payload = sharing.validate_payload(sharing.build_payload(rich))
        for i in range(sharing.MAX_PILES_PER_USER):
            Pile.objects.create(user=user, name=f"bulk{i}")
        before = Pile.objects.filter(user=user).count()
        with pytest.raises(sharing.TemplateError):
            sharing.import_template(user, payload, month="2027-06", amounts={})
        assert Pile.objects.filter(user=user).count() == before

    @staticmethod
    def _fill(rich, payload=None) -> dict:
        payload = sharing.validate_payload(payload or sharing.build_payload(rich))
        return {n: "1000" for n in sharing.ImportForm(payload).fields if n != "month"}


class TestViews:
    def test_everything_needs_a_login(self, client):
        for name, kwargs in (
            ("share", {}),
            ("share_export", {}),
            ("import_file", {}),
            ("template", {"token": "abc"}),
        ):
            resp = client.get(reverse(f"planner:{name}", kwargs=kwargs))
            assert resp.status_code == HTTPStatus.FOUND
            assert "login" in resp.url

    def test_create_a_link_then_preview_it_as_someone_else(
        self,
        client_in,
        rich,
        client,
    ):
        resp = client_in.post(
            reverse("planner:share"),
            {"action": "create", "title": "My plan", "description": "<b>hi</b>"},
        )
        assert resp.status_code == HTTPStatus.FOUND
        share = SharedTemplate.objects.get(owner=rich)
        assert len(share.token) >= 20
        _other, other_client = other_user_client(type(client))
        page = other_client.get(
            reverse("planner:template", kwargs={"token": share.token}),
        )
        html = page.content.decode()
        assert page.status_code == HTTPStatus.OK
        assert "My plan" in html
        assert "<b>hi</b>" not in html  # escaped
        assert "&lt;b&gt;hi&lt;/b&gt;" in html
        assert rich.email not in html
        assert "98765" not in html
        assert 'name="cap_' in html  # asks for the cap amount

    def test_a_wrong_token_is_404_and_anonymous_is_sent_to_login(
        self,
        client_in,
        client,
    ):
        assert (
            client_in.get(
                reverse("planner:template", kwargs={"token": "nope"}),
            ).status_code
            == HTTPStatus.NOT_FOUND
        )
        anonymous = type(client)()
        resp = anonymous.get(reverse("planner:template", kwargs={"token": "nope"}))
        assert resp.status_code == HTTPStatus.FOUND
        assert "login" in resp.url

    def test_deleting_a_link_kills_it_and_only_the_owner_can(
        self,
        client_in,
        rich,
        client,
    ):
        client_in.post(reverse("planner:share"), {"action": "create", "title": "T"})
        share = SharedTemplate.objects.get()
        _other, other_client = other_user_client(type(client))
        other_client.post(
            reverse("planner:share"),
            {"action": "delete", "id": share.pk},
        )
        assert SharedTemplate.objects.filter(pk=share.pk).exists()
        client_in.post(reverse("planner:share"), {"action": "delete", "id": share.pk})
        assert not SharedTemplate.objects.exists()
        assert (
            client_in.get(
                reverse("planner:template", kwargs={"token": share.token}),
            ).status_code
            == HTTPStatus.NOT_FOUND
        )

    def test_link_limit(self, client_in, rich):
        for i in range(sharing.MAX_LINKS_PER_USER):
            SharedTemplate.objects.create(owner=rich, title=f"t{i}", payload={})
        client_in.post(
            reverse("planner:share"),
            {"action": "create", "title": "one too many"},
        )
        assert (
            SharedTemplate.objects.filter(owner=rich).count()
            == sharing.MAX_LINKS_PER_USER
        )

    def test_title_is_required(self, client_in, rich):
        client_in.post(reverse("planner:share"), {"action": "create", "title": "  "})
        assert not SharedTemplate.objects.exists()

    def test_export_is_a_json_download_without_money(self, client_in, rich):
        resp = client_in.get(reverse("planner:share_export"))
        assert "attachment" in resp["Content-Disposition"]
        data = json.loads(resp.content)
        assert data["schema"] == sharing.SCHEMA_VERSION
        assert "98765" not in resp.content.decode()

    def test_full_import_from_a_link(self, client_in, rich, client):
        client_in.post(reverse("planner:share"), {"action": "create", "title": "T"})
        share = SharedTemplate.objects.get()
        other, other_client = other_user_client(type(client))
        url = reverse("planner:template", kwargs={"token": share.token})
        html = other_client.get(url).content.decode()
        import re

        names = set(re.findall(r'name="((?:cap|target|cond)_[^"]+)"', html))
        data = {"month_year": "2027", "month_month": "7", **dict.fromkeys(names, "500")}
        resp = other_client.post(url, data)
        assert resp.status_code == HTTPStatus.FOUND
        assert other.piles.filter(name="Trip").exists()
        assert other.plan_periods.filter(effective_month="2027-07").exists()

    def test_a_missing_amount_keeps_you_on_the_page(self, client_in, rich, client):
        client_in.post(reverse("planner:share"), {"action": "create", "title": "T"})
        share = SharedTemplate.objects.get()
        other, other_client = other_user_client(type(client))
        before = other.piles.count()
        resp = other_client.post(
            reverse("planner:template", kwargs={"token": share.token}),
            {"month_year": "2027", "month_month": "7"},
        )
        assert resp.status_code == HTTPStatus.OK
        assert other.piles.count() == before

    def test_upload_preview_and_import(self, client_in, rich, client):
        exported = client_in.get(reverse("planner:share_export")).content
        _other, other_client = other_user_client(type(client))
        resp = other_client.post(
            reverse("planner:share"),
            {
                "action": "upload",
                "file": SimpleUploadedFile(
                    "t.json",
                    exported,
                    content_type="application/json",
                ),
            },
        )
        assert resp.status_code == HTTPStatus.FOUND
        assert resp.url == reverse("planner:import_file")
        assert other_client.get(resp.url).status_code == HTTPStatus.OK

    @pytest.mark.parametrize(
        "content",
        [
            b"not json",
            b"\xff\xfe",
            b"[]",
            b'{"schema": 1, "piles": "x", "plans": []}',
            b"x" * (sharing.MAX_FILE_BYTES + 1),
        ],
    )
    def test_bad_uploads_are_refused(self, client_in, content):
        resp = client_in.post(
            reverse("planner:share"),
            {"action": "upload", "file": SimpleUploadedFile("t.json", content)},
        )
        assert resp.status_code == HTTPStatus.FOUND
        assert resp.url == reverse("planner:share")  # back on the page, nothing stored
        assert "template_import" not in client_in.session

    def test_the_preview_page_without_anything_to_show_goes_back(self, client_in):
        resp = client_in.get(reverse("planner:import_file"))
        assert resp.status_code == HTTPStatus.FOUND
        assert resp.url == reverse("planner:share")

    def test_pages_render_in_thai(self, client_in, rich):
        html = client_in.get(reverse("planner:share")).content.decode()
        assert "แชร์แผน" in html
        assert Salary.objects.filter(user=rich).exists()
