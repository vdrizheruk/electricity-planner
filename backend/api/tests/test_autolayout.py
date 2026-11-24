import pytest

from catalog.models import Product
from panels.layout_db import sync_rails, validate_panel
from panels.models import Placement
from projects.models import ConsumerGroup, Panel, Project

B = "/api/v1"


@pytest.fixture
def apartment(project):
    for name, t, p, ln, extra in (
        ("Свет", "lighting", 800, 25, {}),
        ("Розетки", "sockets", 3000, 20, {}),
        ("Кухня", "kitchen", 3000, 15, {}),
        ("Плита", "cooker", 7000, 15, {}),
        ("Бойлер", "boiler", 2000, 10, {}),
        ("Кондиционер", "ac", 2500, 20, {"cos_phi": "0.9"}),
    ):
        ConsumerGroup.objects.create(
            project=project, name=name, type=t, power_w=p, length_m=ln, **extra
        )
    return project


@pytest.fixture
def main_panel(apartment, seeded):
    return Panel.objects.create(project=apartment, name="ГРЩ", kind="main")


def run(auth, panel, **opts):
    return auth.post(f"{B}/panels/{panel.pk}/autolayout/", opts, format="json")


def kinds(panel):
    return [
        (p.rail.row_index, p.start_module, p.product.category.code, p.product.sku)
        for p in panel.placements.select_related("rail", "product__category")
    ]


def test_autolayout_apartment(auth, main_panel, apartment):
    r = run(auth, main_panel)
    assert r.status_code == 200, r.json()
    body = r.json()
    main_panel.refresh_from_db()
    assert body["enclosure_changed"] and body["enclosure"] == main_panel.enclosure_id
    assert main_panel.enclosure.electrical["total_modules"] >= 24
    assert body["capacity_modules"] >= body["required_modules"] * 1.2 - 1e-9
    # everything valid, every group linked to exactly one breaker-ish device
    assert validate_panel(main_panel) == []
    placed = main_panel.placements.select_related("product__category")
    assert {p.group.name for p in placed if p.group} == {
        "Свет",
        "Розетки",
        "Кухня",
        "Плита",
        "Бойлер",
        "Кондиционер",
    }
    assert auth.get(f"{B}/panels/{main_panel.pk}/unplaced/").json() == []
    # input chain first: main 2P breaker (63 A), voltage relay, SPD, in this order
    first = [c for _, _, c, _ in kinds(main_panel)][:3]
    assert first == ["mcb", "voltage_relay", "spd"]
    main = placed.order_by("rail__row_index", "start_module").first()
    assert main.product.poles == 2 and main.product.rated_a == 63
    cats = [p.product.category.code for p in placed]
    assert cats.count("rcbo") == 3  # cooker, boiler, ac
    assert cats.count("rcd") == 1  # sockets + kitchen share one RCD
    # shared RCD stands directly before its two breakers
    order = [p for p in placed.order_by("rail__row_index", "start_module")]
    i = next(n for n, p in enumerate(order) if p.product.category.code == "rcd")
    assert {order[i + 1].group.name, order[i + 2].group.name} == {"Розетки", "Кухня"}
    # results were saved on the groups
    cooker = ConsumerGroup.objects.get(name="Плита")
    assert cooker.breaker_a == 32 and cooker.panel_id == main_panel.pk


def test_autolayout_is_idempotent_and_keeps_mounting_panel_items(auth, main_panel, contactor):
    first = run(auth, main_panel).json()
    main_panel.refresh_from_db()
    Placement.objects.create(
        panel=main_panel, product=contactor, x_mm=10, y_mm=10, w_mm=55, h_mm=85
    )
    n_din = main_panel.placements.filter(rail__isnull=False).count()
    second = run(auth, main_panel)
    assert second.status_code == 200 and not second.json()["enclosure_changed"]
    assert (
        main_panel.placements.filter(rail__isnull=False).count()
        == n_din
        == len([p for p in first["placements"]])
    )
    assert main_panel.placements.filter(rail__isnull=True).count() == 1


def test_curve_substitution_is_reported(auth, main_panel):
    body = run(auth, main_panel).json()
    codes = {(f["code"], f["group_id"]) for f in body["findings"]}
    cooker = ConsumerGroup.objects.get(name="Плита")  # calc picks B32, RCBO catalog has C
    assert ("curve_substituted", cooker.pk) in codes


def test_not_enough_room_without_pick(auth, main_panel, enclosure):
    small = Product.objects.get(brand__name="Hager", sku="VF-12")
    main_panel.enclosure = small
    main_panel.save()
    sync_rails(main_panel)
    r = run(auth, main_panel, pick_enclosure=False)
    assert r.status_code == 409 and r.json()["code"] == "enclosure_too_small"
    assert main_panel.placements.count() == 0


def test_bigger_enclosure_is_picked_when_too_small(auth, main_panel):
    small = Product.objects.get(brand__name="Hager", sku="VF-12")
    main_panel.enclosure = small
    main_panel.save()
    sync_rails(main_panel)
    r = run(auth, main_panel)
    assert r.status_code == 200 and r.json()["enclosure_changed"]
    main_panel.refresh_from_db()
    assert main_panel.rails.count() >= 2 and main_panel.mounting == "flush"
    assert validate_panel(main_panel) == []


def test_calculation_errors_block_layout(auth, main_panel, apartment):
    apartment.main_breaker_a = 16
    apartment.save()
    r = run(auth, main_panel)
    assert r.status_code == 409 and r.json()["code"] == "calculation_failed"
    assert any(f["code"] == "main_breaker_overload" for f in r.json()["findings"])
    assert main_panel.placements.count() == 0


def test_options(auth, main_panel):
    run(auth, main_panel, voltage_relay=False, spd="none", fire_rcd=True)
    cats = [c for _, _, c, _ in kinds(main_panel)]
    assert "spd" not in cats and "voltage_relay" not in cats
    fire = main_panel.placements.get(product__category__code="rcd", product__leakage_ma=300)
    assert fire.product.poles == 2 and fire.product.electrical["selective"] is True
    assert run(auth, main_panel, spd="bogus").status_code == 400


def test_type1_plus_2_spd(auth, main_panel):
    run(auth, main_panel, spd="1+2")
    spd = main_panel.placements.get(product__category__code="spd").product
    assert spd.electrical["spd_type"] == "1+2"


def test_tier_follows_project_setting(auth, main_panel, apartment):
    apartment.price_tier = "premium"
    apartment.save()
    run(auth, main_panel)
    brands = {
        p.product.brand.name
        for p in main_panel.placements.select_related("product__brand")
        if p.product.category.code == "mcb"
    }
    assert brands <= {"ABB", "Schneider Electric", "Hager"}


def test_three_phase_layout(auth, user):
    project = Project.objects.create(owner=user, name="Дом", grid="3ph", main_breaker_a=40)
    from django.core.management import call_command

    call_command("seed_catalog")
    for i in range(3):
        ConsumerGroup.objects.create(project=project, name=f"R{i}", type="sockets", power_w=2000)
    panel = Panel.objects.create(project=project, name="ГРЩ", kind="main")
    r = run(auth, panel)
    assert r.status_code == 200, r.json()
    main = (
        panel.placements.select_related("product")
        .order_by("rail__row_index", "start_module")
        .first()
    )
    assert main.product.poles == 4 and main.product.rated_a == 40
    rcds = panel.placements.filter(product__category__code="rcd")
    assert rcds.count() == 3  # one 2P RCD per phase
    assert validate_panel(panel) == []
    assert sorted(ConsumerGroup.objects.values_list("assigned_phase", flat=True)) == [
        "L1",
        "L2",
        "L3",
    ]


def test_unassigned_groups_only_go_to_main_panel(auth, apartment, seeded):
    floor = Panel.objects.create(project=apartment, name="Этаж", kind="floor")
    assert run(auth, floor).status_code == 200
    assert not ConsumerGroup.objects.filter(panel__isnull=False).exists()
    assert floor.placements.count() >= 1  # input chain only


def test_other_user_cannot_autolayout(other_client, main_panel):
    assert run(other_client, main_panel).status_code == 404
    assert main_panel.placements.count() == 0


def test_empty_panel_only_has_input_chain(auth, project, seeded):
    panel = Panel.objects.create(project=project, name="ГРЩ", kind="main")
    assert run(auth, panel).status_code == 200
    assert [c for _, _, c, _ in kinds(panel)] == ["mcb", "voltage_relay", "spd"]
