import pytest

from catalog.models import Product
from panels.layout_db import validate_panel
from panels.models import Placement
from power.models import PvArray, PvSystem
from projects.models import Panel, PanelKind

B = "/api/v1"


def sku(brand, s):
    return Product.objects.get(brand__name=brand, sku=s)


def url(project, tail=""):
    return f"{B}/projects/{project.pk}/pv/{tail}"


def cfg(auth, project, **data):
    r = auth.patch(url(project), data, format="json")
    assert r.status_code == 200, r.json()
    return r.json()


def check(auth, project):
    r = auth.get(url(project, "check/"))
    assert r.status_code == 200, r.json()
    return r.json()


def codes(body, level=None):
    return {f["code"] for f in body["findings"] if level in (None, f["level"])}


@pytest.fixture
def setup(auth, project, seeded):
    module = sku("JA Solar", "JAM72S30-550/MR")
    inv = sku("Growatt", "SPH-10000TL3-BH")  # 3ph hybrid, 2 MPPT 140..1000 V
    cfg(
        auth,
        project,
        module=module.pk,
        inverter=inv.pk,
        arrays=[
            {"mppt": 1, "series": 14, "strings": 1, "cable_m": 25},
            {"mppt": 2, "series": 14, "strings": 1, "cable_m": 25},
        ],
    )
    return project


def test_defaults_and_unconfigured_check(auth, project):
    r = auth.get(url(project))
    assert r.status_code == 200 and r.json()["arrays"] == []
    assert PvSystem.objects.filter(project=project).count() == 1
    body = check(auth, project)
    assert body["configured"] is False and body["metrics"] is None
    assert body["total_price"] == "0.00"


def test_arrays_are_replaced_and_unique(auth, project, seeded):
    cfg(auth, project, arrays=[{"mppt": 1, "series": 10}, {"mppt": 2, "series": 12}])
    assert PvArray.objects.filter(pv__project=project).count() == 2
    cfg(auth, project, arrays=[{"mppt": 1, "series": 8, "strings": 2}])
    arrays = auth.get(url(project)).json()["arrays"]
    assert [(a["mppt"], a["series"], a["strings"]) for a in arrays] == [(1, 8, 2)]
    r = auth.patch(url(project), {"arrays": [{"mppt": 1}, {"mppt": 1}]}, format="json")
    assert r.status_code == 400
    # a PATCH without arrays leaves them alone
    cfg(auth, project, green_tariff=True)
    assert PvArray.objects.filter(pv__project=project).count() == 1


@pytest.mark.parametrize(
    "body",
    [
        {"arrays": [{"mppt": 1, "series": 0}]},
        {"arrays": [{"mppt": 1, "tilt_deg": 120}]},
        {"t_min_c": -90},
        {"performance_ratio": 1.5},
        {"region": "mars"},
        {"inverter_count": 0},
    ],
)
def test_invalid_input_rejected(auth, project, body):
    assert auth.patch(url(project), body, format="json").status_code == 400


def test_module_must_be_a_pv_module(auth, project, seeded):
    other = sku("Growatt", "SPH-10000TL3-BH")
    assert auth.patch(url(project), {"module": other.pk}, format="json").status_code == 400


def test_check_good_configuration(auth, setup):
    body = check(auth, setup)
    assert body["configured"] and body["ok"], body["findings"]
    assert body["metrics"]["modules"] == 28
    assert body["metrics"]["kwp"] == pytest.approx(15.4)
    assert len(body["arrays"]) == 2 and body["arrays"][0]["voc_cold_v"] > 0
    kinds = {c["kind"] for c in body["components"]}
    assert {"pv_module", "inverter", "dc_isolator", "dc_spd", "cable", "mcb"} <= kinds
    assert all(c["product"] for c in body["components"]), [
        c["role"] for c in body["components"] if not c["product"]
    ]
    assert float(body["total_price"]) > 0
    spd = next(c for c in body["components"] if c["kind"] == "dc_spd")
    assert spd["product"]["electrical"]["ucpv_v"] >= body["arrays"][0]["voc_cold_v"]


def test_check_reports_voltage_and_current_errors(auth, setup):
    cfg(auth, setup, arrays=[{"mppt": 1, "series": 20, "strings": 1}])  # Voc cold > 1000 V
    assert "VOC_COLD" in codes(check(auth, setup), "error")
    cfg(auth, setup, arrays=[{"mppt": 1, "series": 14, "strings": 2}])  # 28 A > 20 A
    body = check(auth, setup)
    assert "ISC_HIGH" in codes(body, "error") and not body["ok"]


def test_check_dc_ac_warning(auth, setup):
    cfg(auth, setup, arrays=[{"mppt": 1, "series": 18, "strings": 1}, {"mppt": 2, "series": 18}])
    body = check(auth, setup)
    assert "DC_AC_HIGH" in codes(body, "warning")  # 19.8 kWp on 10 kW


def test_offgrid_inverter_has_no_mppt(auth, setup):
    cfg(auth, setup, inverter=sku("Victron Energy", "MultiPlus-II-48/5000/70-50").pk)
    assert "NO_MPPT" in codes(check(auth, setup), "error")


def test_green_tariff_adds_bidirectional_meter(auth, setup):
    body = check(auth, setup)
    assert not [c for c in body["components"] if c["kind"] == "meter"]
    cfg(auth, setup, green_tariff=True)
    meter = next(c for c in check(auth, setup)["components"] if c["kind"] == "meter")
    assert meter["product"]["electrical"]["bidirectional"] is True


def test_fuses_for_three_strings(auth, project, seeded):
    cfg(
        auth,
        project,
        module=sku("JA Solar", "JAM54S30-410/MR").pk,
        inverter=sku("Huawei", "SUN2000-15KTL-M2").pk,
        arrays=[{"mppt": 1, "series": 12, "strings": 3}],
    )
    body = check(auth, project)
    fuse = next(c for c in body["components"] if c["kind"] == "dc_fuse")
    assert fuse["qty"] == 6 and fuse["product"]["rated_a"] == "25.00"  # 1.5 x 13.9 = 20.85 -> 25 A
    assert float(fuse["product"]["electrical"]["vdc_max"]) >= body["arrays"][0]["voc_cold_v"]


def test_apply_builds_dc_box(auth, setup):
    r = auth.post(url(setup, "apply/"))
    assert r.status_code == 201, r.json()
    panel = Panel.objects.get(project=setup, kind=PanelKind.DC)
    assert panel.name == "DC-бокс"
    roles = set(Placement.objects.filter(panel=panel).values_list("label", flat=True))
    assert {"DC QS", "DC УЗИП", "AC выход", "AC УЗИП"} <= roles
    assert validate_panel(panel) == []
    # rebuilding does not duplicate
    assert auth.post(url(setup, "apply/")).status_code == 201
    assert Panel.objects.filter(project=setup, kind=PanelKind.DC).count() == 1


def test_apply_rejected_when_not_ready_or_invalid(auth, project, setup):
    cfg(auth, setup, arrays=[{"mppt": 1, "series": 20}])
    r = auth.post(url(setup, "apply/"))
    assert r.status_code == 409 and r.json()["code"] == "has_errors"
    cfg(auth, setup, module=None)
    r = auth.post(url(setup, "apply/"))
    assert r.status_code == 409 and r.json()["code"] == "empty"


def test_pv_endpoints_hide_foreign_projects(auth, other_client, setup):
    for tail in ("", "check/"):
        assert other_client.get(url(setup, tail)).status_code == 404
    assert other_client.patch(url(setup), {}, format="json").status_code == 404
    assert other_client.post(url(setup, "apply/")).status_code == 404


def test_pv_requires_auth(client, project):
    assert client.get(url(project)).status_code in (401, 403)
