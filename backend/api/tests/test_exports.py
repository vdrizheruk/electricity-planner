from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from catalog.models import Product
from panels.models import Placement
from power.models import PowerSystem, PvSystem

B = "/api/v1"
PIXEL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
    '<rect width="200" height="100" fill="#cde"/></svg>'
)


def sku(brand, s):
    return Product.objects.get(brand__name=brand, sku=s)


def url(project, tail):
    return f"{B}/projects/{project.pk}/{tail}"


@pytest.fixture
def board(project, panel, rails, mcb, mcb3):
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb, start_module=0, width_modules=1
    )
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb, start_module=1, width_modules=1
    )
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb3, start_module=2, width_modules=3
    )
    return project


def pages(pdf: bytes) -> int:
    return len(PdfReader(BytesIO(pdf)).pages)


def text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


def test_bom_of_empty_project(auth, project):
    r = auth.get(url(project, "bom/"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == "0.00" and body["currency"] == "UAH"
    assert [s["key"] for s in body["sections"]] == ["boards"]


def test_bom_counts_enclosure_and_devices(auth, board, enclosure, mcb, mcb3):
    body = auth.get(url(board, "bom/")).json()
    block = body["sections"][0]["blocks"][0]
    by_sku = {ln["sku"]: ln for ln in block["lines"]}
    assert by_sku[mcb.sku]["qty"] == 2 and by_sku[enclosure.sku]["qty"] == 1
    expected = enclosure.price + 2 * mcb.price + mcb3.price
    assert Decimal(block["total"]) == expected.quantize(Decimal("0.01"))
    assert body["total"] == block["total"] == body["sections"][0]["total"]


def test_bom_solar_estimated_then_not_double_counted(auth, board):
    auth.patch(
        f"{B}/projects/{board.pk}/pv/",
        {
            "module": sku("JA Solar", "JAM72S30-550/MR").pk,
            "inverter": sku("Growatt", "SPH-10000TL3-BH").pk,
            "arrays": [{"mppt": 1, "series": 14}, {"mppt": 2, "series": 14}],
        },
        format="json",
    )
    before = auth.get(url(board, "bom/")).json()
    solar = next(s for s in before["sections"] if s["key"] == "solar")
    assert solar["blocks"][0]["estimated"] is True
    roles = {ln["sku"] for ln in solar["blocks"][0]["lines"]}
    assert "JAM72S30-550/MR" in roles and "SPH-10000TL3-BH" in roles
    assert any(ln["unit"] == "м" for ln in solar["blocks"][0]["lines"])  # PV cable is in metres
    assert any("OTDC" in sku_ for sku_ in roles)  # DC isolator counted from the scheme

    assert auth.post(url(board, "pv/apply/")).status_code == 201
    after = auth.get(url(board, "bom/")).json()
    solar2 = next(s for s in after["sections"] if s["key"] == "solar")
    assert solar2["blocks"][0]["estimated"] is False
    assert not any("OTDC" in ln["sku"] for ln in solar2["blocks"][0]["lines"])  # now in DC box
    boards2 = next(s for s in after["sections"] if s["key"] == "boards")
    dc = next(b for b in boards2["blocks"] if b["title"] == "DC-бокс")
    assert any("OTDC" in ln["sku"] for ln in dc["lines"])
    assert Decimal(after["total"]) == Decimal(boards2["total"]) + Decimal(solar2["total"])


def test_bom_backup_section_and_shared_inverter(auth, board):
    inv = sku("Growatt", "SPH-10000TL3-BH")
    ps = PowerSystem.objects.create(
        project=board,
        scenario="grid_inverter",
        inverter=inv,
        battery=sku("Pylontech", "US5000"),
        battery_count=2,
    )
    body = auth.get(url(board, "bom/")).json()
    backup = next(s for s in body["sections"] if s["key"] == "backup")
    lines = {ln["sku"]: ln for ln in backup["blocks"][0]["lines"]}
    assert lines["US5000"]["qty"] == 2 and lines["SPH-10000TL3-BH"]["qty"] == 1
    # the same hybrid inverter used for PV is not counted twice
    PvSystem.objects.create(project=board, module=sku("JA Solar", "JAM72S30-550/MR"), inverter=inv)
    ps.save()
    body = auth.get(url(board, "bom/")).json()
    backup = next(s for s in body["sections"] if s["key"] == "backup")
    assert "SPH-10000TL3-BH" not in {ln["sku"] for ln in backup["blocks"][0]["lines"]}


def test_bom_ignores_equipment_of_unused_scenario(auth, board):
    PowerSystem.objects.create(
        project=board, scenario="grid_gen_ats", battery=sku("Pylontech", "US5000")
    )
    body = auth.get(url(board, "bom/")).json()
    assert [s["key"] for s in body["sections"]] == ["boards"]  # a battery without inverter scenario


def test_xlsx_export(auth, board, enclosure):
    r = auth.get(url(board, "export/xlsx/"))
    assert r.status_code == 200
    assert r["Content-Type"].startswith("application/vnd.openxmlformats")
    assert f"specification-{board.pk}.xlsx" in r["Content-Disposition"]
    ws = load_workbook(BytesIO(r.content)).active
    cells = [[c.value for c in row] for row in ws.iter_rows()]
    flat = [v for row in cells for v in row if v is not None]
    assert "Спецификация: Квартира" in flat and "Щиты" in flat and "Всего, ₴" in flat
    header = next(row for row in cells if row[:3] == ["№", "Бренд", "Артикул"])
    assert header[7] == "Сумма, ₴"
    body = auth.get(url(board, "bom/")).json()
    grand = next(row for row in cells if row[3] == "Всего, ₴")[7]
    assert grand == pytest.approx(float(body["total"]))
    enc = next(row for row in cells if row[2] and str(row[2]).startswith(enclosure.sku))
    assert enc[5] == 1 and enc[7] == pytest.approx(float(enclosure.price))


def test_pdf_get_is_a_valid_pdf(auth, board):
    r = auth.get(url(board, "export/pdf/"))
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and pages(r.content) >= 1
    content = text(r.content)
    assert "Спецификация: Квартира" in content and "Щиты" in content and "Всего" in content


def test_pdf_post_adds_drawing_pages(auth, board, panel):
    plain = auth.get(url(board, "export/pdf/")).content
    body = {
        "images": [
            {"panel_id": panel.pk, "kind": "board", "svg": PIXEL_SVG},
            {"panel_id": panel.pk, "kind": "diagram", "svg": PIXEL_SVG},
        ]
    }
    r = auth.post(url(board, "export/pdf/"), body, format="json")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert pages(r.content) == pages(plain) + 1  # both pictures share one drawing page


def test_pdf_ignores_foreign_panel_ids_and_rejects_bad_svg(auth, board, panel):
    r = auth.post(
        url(board, "export/pdf/"),
        {"images": [{"panel_id": 999999, "kind": "board", "svg": PIXEL_SVG}]},
        format="json",
    )
    assert r.status_code == 200
    plain = auth.get(url(board, "export/pdf/")).content
    assert pages(r.content) == pages(plain)
    for bad in (
        {"panel_id": panel.pk, "kind": "board", "svg": "<html>nope</html>"},
        {"panel_id": panel.pk, "kind": "other", "svg": PIXEL_SVG},
        {"panel_id": panel.pk, "kind": "board", "svg": "<svg " + "x" * 2_000_001},
    ):
        assert (
            auth.post(url(board, "export/pdf/"), {"images": [bad]}, format="json").status_code
            == 400
        )


def test_pdf_does_not_fetch_external_or_local_resources(auth, board, panel, tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not an image")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="50" height="50">'
        f'<image href="file://{secret}" width="10" height="10"/>'
        '<image href="http://127.0.0.1:9/x.png" width="10" height="10"/></svg>'
    )
    r = auth.post(
        url(board, "export/pdf/"),
        {"images": [{"panel_id": panel.pk, "kind": "board", "svg": svg}]},
        format="json",
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


@pytest.mark.parametrize("tail", ["bom/", "export/xlsx/", "export/pdf/"])
def test_exports_hide_foreign_projects(auth, other_client, board, tail):
    assert other_client.get(url(board, tail)).status_code == 404


def test_pdf_post_hides_foreign_projects_and_requires_auth(client, other_client, board):
    assert (
        other_client.post(url(board, "export/pdf/"), {"images": []}, format="json").status_code
        == 404
    )
    assert client.get(url(board, "bom/")).status_code in (401, 403)
    assert client.get(url(board, "export/pdf/")).status_code in (401, 403)
