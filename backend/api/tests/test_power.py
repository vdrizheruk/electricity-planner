import pytest

from catalog.models import Product
from panels.layout_db import validate_panel
from panels.models import Placement
from power.models import PowerSystem
from projects.models import ConsumerGroup, Panel

B = "/api/v1"


@pytest.fixture
def home(project, seeded):
    for name, t, p, backed in (
        ("Свет", "lighting", 400, True),
        ("Розетки", "sockets", 3000, True),
        ("Кондиционер", "ac", 2000, True),
        ("Бойлер", "boiler", 2000, False),
    ):
        ConsumerGroup.objects.create(
            project=project, name=name, type=t, power_w=p, backed_up=backed, cos_phi="0.8"
        )
    return project


def sku(brand, s):
    return Product.objects.get(brand__name=brand, sku=s)


def cfg(auth, project, **data):
    r = auth.patch(f"{B}/projects/{project.pk}/power/", data, format="json")
    assert r.status_code == 200, r.json()
    return r.json()


def check(auth, project):
    r = auth.get(f"{B}/projects/{project.pk}/power/check/")
    assert r.status_code == 200, r.json()
    return r.json()


def codes(body, level=None):
    return {f["code"] for f in body["findings"] if level in (None, f["level"])}


def test_defaults_created_on_first_get(auth, home):
    r = auth.get(f"{B}/projects/{home.pk}/power/")
    assert r.status_code == 200
    assert r.json()["scenario"] == "grid1_gen1" and r.json()["ats_kind"] == "none"
    assert PowerSystem.objects.filter(project=home).count() == 1
    auth.get(f"{B}/projects/{home.pk}/power/")
    assert PowerSystem.objects.filter(project=home).count() == 1


def test_three_phase_project_defaults_to_three_phase_scenario(auth, home):
    home.grid = "3ph"
    home.save()
    assert auth.get(f"{B}/projects/{home.pk}/power/").json()["scenario"] == "grid_gen_ats"


def test_generator_without_ats_is_reported_as_parallel_hazard(auth, home):
    cfg(auth, home, generator=sku("Hyundai", "HHY-7000FE").pk)
    body = check(auth, home)
    assert "PARALLEL_GEN_GRID" in codes(body, "error") and not body["ok"]


def test_check_selects_products_and_prices(auth, home):
    cfg(
        auth,
        home,
        generator=sku("Hyundai", "DHY-8500SE").pk,
        ats_kind="contactor",
        ats_poles=2,
        ats_rated_a=32,
        mechanical_interlock=True,
        electrical_interlock=True,
    )
    body = check(auth, home)
    assert body["ok"], body["findings"]
    by_kind = {(c["role"], c["kind"]): c for c in body["components"]}
    ats = by_kind[("ats", "contactor")]
    assert ats["qty"] == 2 and ats["product"]["category"]["code"] == "contactor"
    assert ats["product"]["poles"] == 2 and ats["product"]["din_mountable"]
    assert by_kind[("ats", "interlock")]["product"]["electrical"]["mechanical_interlock"]
    assert by_kind[("gen_in_breaker", "mcb")]["product"]["rated_a"] == "40.00"  # 8.1 kVA = 35 A
    assert by_kind[("spd", "spd")]["product"] is not None
    expected = sum(float(c["price_total"]) for c in body["components"])
    assert float(body["total_price"]) == pytest.approx(expected)
    # (1500 + 320*... ) demand: lighting 320 + sockets 1500 + ac (2000 W*0.8 Kc) = 3420 W
    assert body["metrics"]["p_backup_w"] == pytest.approx(3420)


def test_inverter_scenario_with_battery(auth, home):
    cfg(
        auth,
        home,
        scenario="grid_inverter",
        inverter=sku("Deye", "SUN-5K-SG03LP1-EU").pk,
        battery=sku("Pylontech", "US5000").pk,
        battery_count=2,
    )
    body = check(auth, home)
    assert body["ok"], body["findings"]
    m = body["metrics"]
    assert m["inverter_capacity_w"] == 5000
    assert m["autonomy_h"] == pytest.approx(2 * 4.8 * 0.9 * 0.9 / 3.42)
    roles = {c["role"] for c in body["components"]}
    assert {"inv_in_breaker", "inv_out_breaker", "rcd_inv_out", "battery_dc_breaker"} <= roles
    rcd = next(c for c in body["components"] if c["role"] == "rcd_inv_out")
    assert rcd["product"]["leakage_ma"] == 30
    dc = next(c for c in body["components"] if c["role"] == "battery_dc_breaker")
    assert dc["product"]["category"]["code"] == "dc_breaker"


def test_on_grid_inverter_is_rejected(auth, home):
    cfg(auth, home, scenario="grid_inverter", inverter=sku("Growatt", "MIN-5000TL-X").pk)
    assert "INVERTER_NOT_BACKUP" in codes(check(auth, home), "error")


def test_power_config_validation(auth, home):
    url = f"{B}/projects/{home.pk}/power/"
    mcb = Product.objects.filter(category__code="mcb").first()
    assert auth.patch(url, {"generator": mcb.pk}, format="json").status_code == 400
    assert auth.patch(url, {"scenario": "nope"}, format="json").status_code == 400
    assert auth.patch(url, {"ats_poles": 5}, format="json").status_code == 400
    assert auth.patch(url, {"inverter_count": 0}, format="json").status_code == 400
    assert auth.patch(url, {"autonomy_target_h": -1}, format="json").status_code == 400
    assert auth.patch(url, {"backup_phase": "L4"}, format="json").status_code == 400


def test_power_endpoints_hide_foreign_projects(auth, other_client, home):
    for url in ("/power/", "/power/check/"):
        assert other_client.get(f"{B}/projects/{home.pk}{url}").status_code == 404
    assert (
        other_client.patch(f"{B}/projects/{home.pk}/power/", {}, format="json").status_code == 404
    )
    assert (
        other_client.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json").status_code
        == 404
    )


def test_anonymous_has_no_access(client, home):
    assert client.get(f"{B}/projects/{home.pk}/power/").status_code in (401, 403)


def test_apply_blocked_while_errors_exist(auth, home):
    cfg(auth, home, generator=sku("Hyundai", "HHY-7000FE").pk)  # no ATS
    r = auth.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "has_errors"
    assert any(f["code"] == "PARALLEL_GEN_GRID" for f in r.json()["findings"])
    assert not Panel.objects.filter(project=home, kind="backup").exists()


def test_apply_without_sources_is_rejected(auth, home):
    r = auth.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json")
    assert r.status_code == 409


def test_apply_builds_a_valid_backup_panel(auth, home):
    cfg(
        auth,
        home,
        generator=sku("Hyundai", "DHY-8500SE").pk,
        ats_kind="contactor",
        ats_poles=2,
        ats_rated_a=32,
        mechanical_interlock=True,
        electrical_interlock=True,
    )
    r = auth.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json")
    assert r.status_code == 201, r.json()
    panel = Panel.objects.get(project=home, kind="backup")
    assert panel.enclosure is not None and panel.rails.count() >= 1
    labels = sorted(p.label for p in Placement.objects.filter(panel=panel))
    assert labels == sorted(["АВР", "АВР", "АВР", "Ввод генератор", "Ввод сеть", "УЗИП"])
    assert validate_panel(panel) == []
    # the mechanical interlock and non-DIN parts sit on the mounting panel or rails, never overlap
    body = r.json()
    assert body["panel"]["id"] == panel.pk and len(body["placements"]) == 6
    # applying again rebuilds the same panel instead of duplicating it
    auth.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json")
    assert Panel.objects.filter(project=home, kind="backup").count() == 1
    assert Placement.objects.filter(panel=panel).count() == 6


def test_apply_inverter_scheme_keeps_all_devices_valid(auth, home):
    cfg(
        auth,
        home,
        scenario="grid_inverter",
        inverter=sku("Deye", "SUN-5K-SG03LP1-EU").pk,
        battery=sku("Pylontech", "US5000").pk,
        battery_count=2,
    )
    r = auth.post(f"{B}/projects/{home.pk}/power/apply/", {}, format="json")
    assert r.status_code == 201, r.json()
    panel = Panel.objects.get(project=home, kind="backup")
    assert validate_panel(panel) == []
    cats = {p.product.category.code for p in Placement.objects.filter(panel=panel)}
    assert {"mcb", "rcd", "dc_breaker", "spd"} <= cats


def test_catalog_has_switching_equipment(seeded):
    assert Product.objects.filter(category__code="contactor", poles=4, rated_a=63).exists()
    assert Product.objects.filter(
        category__code="ats", poles=2, electrical__automatic=True
    ).exists()
    assert Product.objects.filter(category__code="ats", electrical__manual=True, poles=4).exists()
    assert Product.objects.filter(category__code="generator", electrical__phases=3).count() >= 2


def sim(auth, project, **q):
    r = auth.get(f"{B}/projects/{project.pk}/power/simulate/", q)
    assert r.status_code == 200, r.json()
    return r.json()


def test_simulate_grid_on_all_groups_powered(auth, home):
    body = sim(auth, home)
    assert all(g["powered"] for g in body["groups"]) and body["dark_w"] == 0


def test_simulate_grid_lost_with_generator_on_ats(auth, home):
    cfg(
        auth,
        home,
        generator=sku("Hyundai", "HHY-7000FE").pk,
        ats_kind="modular",
        ats_poles=2,
        ats_rated_a=40,
    )
    body = sim(auth, home, grid="false", generator="true")
    by = {g["name"]: g for g in body["groups"]}
    assert by["Свет"]["powered"] and by["Свет"]["source"] == "generator"
    assert not by["Бойлер"]["powered"] and by["Бойлер"]["reason"] == "not_backed_up"
    assert body["backup_source"] == "generator"


def test_simulate_validates_switches_and_ownership(auth, home):
    r = auth.get(f"{B}/projects/{home.pk}/power/simulate/", {"position": "x"})
    assert r.status_code == 400
    assert auth.get(f"{B}/projects/999999/power/simulate/").status_code == 404
