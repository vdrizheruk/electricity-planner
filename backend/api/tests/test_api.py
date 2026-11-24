import io

from django.core.management import call_command
from rest_framework.test import APIClient

from catalog.models import Product
from panels.models import DinRail, Placement
from projects.models import ConsumerGroup, Panel, Project

B = "/api/v1"


# ------------------------------------------------------------------ schema
def test_schema_is_valid_without_warnings(db, tmp_path):
    out = tmp_path / "schema.yml"
    call_command("spectacular", "--fail-on-warn", "--file", str(out), stderr=io.StringIO())
    assert out.stat().st_size > 1000


def test_docs_and_schema_endpoints(auth):
    assert auth.get(f"{B}/schema/").status_code == 200
    assert auth.get(f"{B}/docs/").status_code == 200


# -------------------------------------------------------------------- auth
def test_register_login_logout_flow(db):
    c = APIClient(enforce_csrf_checks=True)
    body = {"email": "new@example.com", "password": "S3cure-pass-77!"}
    assert c.post(f"{B}/auth/register/", body).status_code == 403  # CSRF enforced
    token = c.get(f"{B}/auth/csrf/").json()["csrfToken"]
    r = c.post(f"{B}/auth/register/", body, HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 201 and r.json()["email"] == "new@example.com"
    assert c.get(f"{B}/auth/me/").json()["email"] == "new@example.com"
    token = c.cookies["csrftoken"].value
    assert c.post(f"{B}/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert c.get(f"{B}/auth/me/").status_code == 403
    token = c.get(f"{B}/auth/csrf/").json()["csrfToken"]
    bad = c.post(f"{B}/auth/login/", {**body, "password": "wrong"}, HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400
    ok = c.post(f"{B}/auth/login/", body, HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200


def test_register_validation(db):
    c = APIClient()
    assert (
        c.post(f"{B}/auth/register/", {"email": "x@example.com", "password": "123"}).status_code
        == 400
    )
    assert (
        c.post(f"{B}/auth/register/", {"email": "nope", "password": "S3cure-pass-77!"}).status_code
        == 400
    )
    ok = {"email": "dup@example.com", "password": "S3cure-pass-77!"}
    assert c.post(f"{B}/auth/register/", ok).status_code == 201
    assert (
        APIClient().post(f"{B}/auth/register/", {**ok, "email": "DUP@example.com"}).status_code
        == 400
    )


def test_anonymous_has_no_access(client, project, panel):
    for url in (
        f"{B}/projects/",
        f"{B}/projects/{project.pk}/",
        f"{B}/panels/{panel.pk}/",
        f"{B}/catalog/products/",
    ):
        assert client.get(url).status_code in (401, 403)


# --------------------------------------------------------------- ownership
def test_projects_crud_and_isolation(auth, other_client, project):
    r = auth.post(f"{B}/projects/", {"name": "Дом", "grid": "3ph"})
    assert r.status_code == 201 and r.json()["grid"] == "3ph"
    assert auth.get(f"{B}/projects/").json()["count"] == 2
    assert other_client.get(f"{B}/projects/").json()["count"] == 0
    for method, url in (("get", ""), ("patch", ""), ("delete", ""), ("get", "calc/")):
        resp = getattr(other_client, method)(f"{B}/projects/{project.pk}/{url}")
        assert resp.status_code == 404, (method, url)
    assert auth.patch(f"{B}/projects/{project.pk}/", {"name": "Новое"}).json()["name"] == "Новое"
    assert auth.delete(f"{B}/projects/{project.pk}/").status_code == 204


def test_children_isolation(auth, other_client, project, panel, mcb):
    g = ConsumerGroup.objects.create(project=project, name="g", power_w=100)
    pl = Placement.objects.create(
        panel=panel, rail=panel.rails.first(), product=mcb, start_module=0, width_modules=1
    )
    urls = [
        f"{B}/panels/{panel.pk}/",
        f"{B}/groups/{g.pk}/",
        f"{B}/placements/{pl.pk}/",
        f"{B}/panels/{panel.pk}/validate/",
        f"{B}/panels/{panel.pk}/unplaced/",
        f"{B}/panels/{panel.pk}/placements/",
        f"{B}/panels/{panel.pk}/versions/",
        f"{B}/projects/{project.pk}/panels/",
        f"{B}/projects/{project.pk}/groups/",
    ]
    for u in urls:
        assert (
            other_client.get(u).status_code == 404 or other_client.get(u).json().get("count") == 0
        ), u
    assert other_client.post(f"{B}/projects/{project.pk}/panels/", {"name": "x"}).status_code == 404
    assert other_client.post(f"{B}/projects/{project.pk}/groups/autoselect/").status_code == 404
    assert (
        other_client.put(
            f"{B}/panels/{panel.pk}/placements/bulk/", {"placements": []}, format="json"
        ).status_code
        == 404
    )
    assert other_client.delete(f"{B}/placements/{pl.pk}/").status_code == 404
    assert Placement.objects.filter(pk=pl.pk).exists()


# ------------------------------------------------------------------ panels
def test_panel_with_enclosure_creates_rails(auth, project, enclosure):
    r = auth.post(
        f"{B}/projects/{project.pk}/panels/",
        {"name": "Щит", "kind": "main", "enclosure": enclosure.pk},
        format="json",
    )
    assert r.status_code == 201, r.json()
    data = r.json()
    assert [(x["row_index"], x["capacity_modules"]) for x in data["rails"]] == [(0, 12), (1, 12)]
    assert data["ip"] == 40 and data["mounting"] == "flush"
    assert data["mounting_area_mm"] == {"width": 210, "height": 300}


def test_panel_enclosure_must_be_enclosure(auth, project, mcb):
    r = auth.post(f"{B}/projects/{project.pk}/panels/", {"name": "x", "enclosure": mcb.pk})
    assert r.status_code == 400 and "enclosure" in r.json()


def test_panel_unique_name(auth, project, panel):
    r = auth.post(f"{B}/projects/{project.pk}/panels/", {"name": panel.name})
    assert r.status_code == 400


def test_change_enclosure_blocked_when_rail_occupied(auth, panel, rails, mcb):
    Placement.objects.create(
        panel=panel, rail=rails[1], product=mcb, start_module=0, width_modules=1
    )
    small = Product.objects.get(brand__name="Hager", sku="VF-12")
    r = auth.patch(f"{B}/panels/{panel.pk}/", {"enclosure": small.pk}, format="json")
    assert r.status_code == 400
    panel.refresh_from_db()
    assert panel.rails.count() == 2


def test_change_enclosure_when_free(auth, panel):
    big = Product.objects.get(brand__name="Hager", sku="VF-48")
    r = auth.patch(f"{B}/panels/{panel.pk}/", {"enclosure": big.pk}, format="json")
    assert r.status_code == 200 and len(r.json()["rails"]) == 4


def test_panel_links_api(auth, project, panel):
    p2 = Panel.objects.create(project=project, name="Этаж")
    url = f"{B}/projects/{project.pk}/links/"
    assert auth.post(url, {"source": panel.pk, "target": p2.pk}).status_code == 201
    assert auth.post(url, {"source": p2.pk, "target": panel.pk}).status_code == 400  # cycle
    assert auth.post(url, {"source": panel.pk, "target": panel.pk}).status_code == 400
    other = Project.objects.create(owner=project.owner, name="Другой")
    foreign = Panel.objects.create(project=other, name="F")
    assert auth.post(url, {"source": panel.pk, "target": foreign.pk}).status_code == 400
    link_id = auth.get(url).json()["results"][0]["id"]
    assert auth.delete(f"{B}/links/{link_id}/").status_code == 204


# ------------------------------------------------------------------ groups
def test_groups_validation_and_autoselect(auth, project):
    url = f"{B}/projects/{project.pk}/groups/"
    assert (
        auth.post(url, {"name": "x", "type": "sockets", "power_w": 100, "phase": "3ph"}).status_code
        == 400
    )
    assert (
        auth.post(url, {"name": "x", "type": "sockets", "power_w": 100, "phase": "L2"}).status_code
        == 400
    )
    assert auth.post(url, {"name": "x", "type": "sockets", "power_w": 0}).status_code == 400
    assert (
        auth.post(
            url, {"name": "x", "type": "sockets", "power_w": 100, "cos_phi": "1.5"}
        ).status_code
        == 400
    )
    for name, t, p in (("Свет", "lighting", 800), ("Плита", "cooker", 7000)):
        r = auth.post(url, {"name": name, "type": t, "power_w": p, "length_m": "15"})
        assert r.status_code == 201, r.json()
        assert r.json()["breaker_a"] is None
    calc = auth.get(f"{B}/projects/{project.pk}/calc/").json()
    assert calc["ok"] and len(calc["groups"]) == 2
    assert ConsumerGroup.objects.filter(breaker_a__isnull=False).count() == 0  # calc is dry
    res = auth.post(f"{url}autoselect/")
    assert res.status_code == 200 and res.json()["ok"]
    groups = {g["name"]: g for g in auth.get(url).json()["results"]}
    assert groups["Плита"]["breaker_a"] == 32 and float(groups["Плита"]["cable_mm2"]) == 4.0
    assert groups["Свет"]["curve"] == "B"


def test_group_panel_must_belong_to_project(auth, project, user):
    other = Project.objects.create(owner=user, name="Другой")
    foreign = Panel.objects.create(project=other, name="F")
    r = auth.post(
        f"{B}/projects/{project.pk}/groups/",
        {"name": "x", "type": "sockets", "power_w": 100, "panel": foreign.pk},
    )
    assert r.status_code == 400


def test_calc_reports_findings(auth, project):
    project.main_breaker_a = 16
    project.save()
    ConsumerGroup.objects.create(project=project, name="Плита", type="cooker", power_w=7000)
    body = auth.get(f"{B}/projects/{project.pk}/calc/").json()
    assert not body["ok"]
    assert any(f["code"] == "main_breaker_overload" for f in body["findings"])


# -------------------------------------------------------------- placements
def place(auth, panel, **kw):
    return auth.post(f"{B}/panels/{panel.pk}/placements/", kw, format="json")


def test_place_on_rail_autowidth(auth, panel, rails, mcb3):
    r = place(auth, panel, rail=rails[0].pk, product=mcb3.pk, start_module=2)
    assert r.status_code == 201, r.json()
    assert r.json()["width_modules"] == 3


def test_collision_and_edges(auth, panel, rails, mcb, mcb3):
    assert place(auth, panel, rail=rails[0].pk, product=mcb3.pk, start_module=0).status_code == 201
    hit = place(auth, panel, rail=rails[0].pk, product=mcb.pk, start_module=2)
    assert hit.status_code == 400 and hit.json()["layout"][0]["code"] == "collision"
    assert place(auth, panel, rail=rails[0].pk, product=mcb.pk, start_module=3).status_code == 201
    # exactly the last free module is allowed, one past the edge is not
    assert place(auth, panel, rail=rails[0].pk, product=mcb.pk, start_module=11).status_code == 201
    edge = place(auth, panel, rail=rails[0].pk, product=mcb3.pk, start_module=10)
    assert edge.status_code == 400
    codes = {i["code"] for i in edge.json()["layout"]}
    assert "out_of_bounds" in codes or "collision" in codes
    far = place(auth, panel, rail=rails[1].pk, product=mcb3.pk, start_module=10)
    assert far.status_code == 400 and far.json()["layout"][0]["code"] == "out_of_bounds"
    assert Placement.objects.filter(panel=panel).count() == 3


def test_move_between_rails_and_self_overlap_allowed(auth, panel, rails, mcb3):
    pl = place(auth, panel, rail=rails[0].pk, product=mcb3.pk, start_module=0).json()
    # move by one module: overlaps only itself -> must be OK
    r = auth.patch(f"{B}/placements/{pl['id']}/", {"start_module": 1}, format="json")
    assert r.status_code == 200 and r.json()["start_module"] == 1
    r = auth.patch(
        f"{B}/placements/{pl['id']}/", {"rail": rails[1].pk, "start_module": 0}, format="json"
    )
    assert r.status_code == 200
    assert auth.delete(f"{B}/placements/{pl['id']}/").status_code == 204


def test_non_din_rules(auth, panel, rails, contactor, mcb):
    bad = place(auth, panel, rail=rails[0].pk, product=contactor.pk, start_module=0)
    assert bad.status_code == 400
    assert "non_din_on_rail" in {i["code"] for i in bad.json()["layout"]}
    din_off = place(auth, panel, product=mcb.pk, x_mm=0, y_mm=0, w_mm=18, h_mm=90)
    assert din_off.status_code == 400
    assert din_off.json()["layout"][0]["code"] == "din_off_rail"
    ok = place(auth, panel, product=contactor.pk, x_mm=10, y_mm=10, w_mm=55, h_mm=85)
    assert ok.status_code == 201, ok.json()
    overlap = place(auth, panel, product=contactor.pk, x_mm=50, y_mm=50, w_mm=55, h_mm=85)
    assert overlap.status_code == 400 and overlap.json()["layout"][0]["code"] == "collision"
    outside = place(auth, panel, product=contactor.pk, x_mm=180, y_mm=10, w_mm=55, h_mm=85)
    assert outside.status_code == 400
    nogeo = place(auth, panel, product=contactor.pk)
    assert nogeo.status_code == 400  # DB-level shape also guarded by validation


def test_panel_without_enclosure_has_no_mounting_panel(auth, project, contactor):
    bare = Panel.objects.create(project=project, name="Без корпуса")
    r = place(auth, bare, product=contactor.pk, x_mm=0, y_mm=0, w_mm=10, h_mm=10)
    assert r.status_code == 400
    assert r.json()["layout"][0]["code"] == "no_mounting_panel"


def test_group_binding_rules(auth, project, panel, rails, mcb, enclosure, user):
    g = ConsumerGroup.objects.create(project=project, name="Розетки", power_w=2000, panel=panel)
    ok = place(auth, panel, rail=rails[0].pk, product=mcb.pk, start_module=0, group=g.pk)
    assert ok.status_code == 201 and ok.json()["group"] == g.pk
    assert auth.get(f"{B}/panels/{panel.pk}/unplaced/").json() == []
    other = Project.objects.create(owner=user, name="Другой")
    fg = ConsumerGroup.objects.create(project=other, name="чужая", power_w=1)
    bad = place(auth, panel, rail=rails[0].pk, product=mcb.pk, start_module=1, group=fg.pk)
    assert bad.status_code == 400 and "group" in bad.json()
    wrong_type = place(
        auth, panel, rail=rails[0].pk, product=enclosure.pk, start_module=2, group=g.pk
    )
    assert wrong_type.status_code == 400


def test_unplaced_lists_groups_without_placement(auth, project, panel):
    ConsumerGroup.objects.create(project=project, name="A", power_w=1, panel=panel)
    ConsumerGroup.objects.create(project=project, name="B", power_w=1)  # other/no panel
    names = [g["name"] for g in auth.get(f"{B}/panels/{panel.pk}/unplaced/").json()]
    assert names == ["A"]


def test_rail_must_belong_to_panel(auth, panel, mcb, project, enclosure):
    other_panel = Panel.objects.create(project=project, name="P2", enclosure=enclosure)
    from panels.layout_db import sync_rails

    sync_rails(other_panel)
    foreign_rail = other_panel.rails.first()
    r = place(auth, panel, rail=foreign_rail.pk, product=mcb.pk, start_module=0)
    assert r.status_code == 400 and "rail" in r.json()


def test_validate_endpoint_reports_db_inconsistencies(auth, panel, rails, mcb):
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb, start_module=0, width_modules=1
    )
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb, start_module=0, width_modules=1
    )
    body = auth.get(f"{B}/panels/{panel.pk}/validate/").json()
    assert [i["code"] for i in body] == ["collision"]


# ------------------------------------------------------------------- bulk
def item(rail, product, start, **kw):
    return {"rail": rail.pk, "product": product.pk, "start_module": start, **kw}


def test_bulk_replace_state(auth, panel, rails, mcb, mcb3):
    url = f"{B}/panels/{panel.pk}/placements/bulk/"
    r = auth.put(
        url, {"placements": [item(rails[0], mcb3, 0), item(rails[0], mcb, 3)]}, format="json"
    )
    assert r.status_code == 200 and len(r.json()) == 2
    first = r.json()[0]["id"]
    # second save: keep one (moved), drop the other, add a new one
    r = auth.patch(
        url,
        {
            "placements": [
                {**item(rails[0], mcb3, 4), "id": first},
                item(rails[1], mcb, 0, label="QF1"),
            ]
        },
        format="json",
    )
    assert r.status_code == 200
    assert Placement.objects.filter(panel=panel).count() == 2
    moved = Placement.objects.get(pk=first)
    assert moved.start_module == 4
    assert Placement.objects.filter(label="QF1").exists()


def test_bulk_is_atomic(auth, panel, rails, mcb, mcb3):
    url = f"{B}/panels/{panel.pk}/placements/bulk/"
    auth.put(url, {"placements": [item(rails[0], mcb, 0)]}, format="json")
    before = list(Placement.objects.values_list("pk", "start_module"))
    r = auth.put(
        url, {"placements": [item(rails[0], mcb3, 0), item(rails[0], mcb, 1)]}, format="json"
    )  # collision -> nothing changes
    assert r.status_code == 400
    assert "placements" in r.json()
    assert list(Placement.objects.values_list("pk", "start_module")) == before


def test_bulk_rejects_unknown_ids_and_foreign_refs(auth, panel, rails, mcb, project, enclosure):
    url = f"{B}/panels/{panel.pk}/placements/bulk/"
    assert (
        auth.put(
            url, {"placements": [{**item(rails[0], mcb, 0), "id": 999999}]}, format="json"
        ).status_code
        == 400
    )
    other_panel = Panel.objects.create(project=project, name="P2", enclosure=enclosure)
    from panels.layout_db import sync_rails

    sync_rails(other_panel)
    r = auth.put(url, {"placements": [item(other_panel.rails.first(), mcb, 0)]}, format="json")
    assert r.status_code == 400
    assert (
        auth.put(
            url,
            {"placements": [{"rail": rails[0].pk, "product": 99999999, "start_module": 0}]},
            format="json",
        ).status_code
        == 400
    )
    assert auth.put(url, {"placements": "x"}, format="json").status_code == 400


def test_bulk_empty_clears(auth, panel, rails, mcb):
    Placement.objects.create(
        panel=panel, rail=rails[0], product=mcb, start_module=0, width_modules=1
    )
    r = auth.put(f"{B}/panels/{panel.pk}/placements/bulk/", {"placements": []}, format="json")
    assert r.status_code == 200 and r.json() == []
    assert Placement.objects.count() == 0


# --------------------------------------------------------------- versions
def test_versions_snapshot_and_restore(auth, panel, rails, mcb, mcb3):
    url = f"{B}/panels/{panel.pk}/placements/bulk/"
    auth.put(url, {"placements": [item(rails[0], mcb3, 0), item(rails[1], mcb, 5)]}, format="json")
    v1 = auth.post(f"{B}/panels/{panel.pk}/versions/", {"note": "черновик"})
    assert v1.status_code == 201 and v1.json()["number"] == 1
    auth.put(url, {"placements": [item(rails[0], mcb, 0)]}, format="json")
    v2 = auth.post(f"{B}/panels/{panel.pk}/versions/", {})
    assert v2.json()["number"] == 2
    assert [
        v["number"] for v in auth.get(f"{B}/panels/{panel.pk}/versions/").json()["results"]
    ] == [2, 1]
    r = auth.post(f"{B}/versions/{v1.json()['id']}/restore/")
    assert r.status_code == 200 and len(r.json()) == 2
    state = sorted(
        Placement.objects.filter(panel=panel).values_list(
            "rail__row_index", "start_module", "product__sku"
        )
    )
    assert state == [(0, 0, "S203-C32"), (1, 5, "S201-C16")]


def test_restore_fails_if_enclosure_shrunk(auth, panel, rails, mcb):
    auth.put(
        f"{B}/panels/{panel.pk}/placements/bulk/",
        {"placements": [item(rails[1], mcb, 0)]},
        format="json",
    )
    v = auth.post(f"{B}/panels/{panel.pk}/versions/", {}).json()
    auth.put(f"{B}/panels/{panel.pk}/placements/bulk/", {"placements": []}, format="json")
    small = Product.objects.get(brand__name="Hager", sku="VF-12")
    assert (
        auth.patch(f"{B}/panels/{panel.pk}/", {"enclosure": small.pk}, format="json").status_code
        == 200
    )
    r = auth.post(f"{B}/versions/{v['id']}/restore/")
    assert r.status_code == 400
    assert DinRail.objects.filter(panel=panel).count() == 1


# ----------------------------------------------------------------- catalog
def test_catalog_filters(auth, seeded):
    r = auth.get(
        f"{B}/catalog/products/",
        {"category": "mcb", "rated_a": 16, "poles": 1, "curve": "C", "page_size": 100},
    )
    body = r.json()
    assert r.status_code == 200 and body["count"] == 6
    assert {p["brand"]["name"] for p in body["results"]} == {
        "ABB",
        "Schneider Electric",
        "Hager",
        "Eaton",
        "IEK",
        "E.NEXT",
    }
    only = auth.get(f"{B}/catalog/products/", {"category": "mcb", "brand": "iek"}).json()
    assert only["count"] == 16 and all(p["brand"]["slug"] == "iek" for p in only["results"])
    q = auth.get(f"{B}/catalog/products/", {"q": "S201-C16"}).json()
    assert {p["sku"] for p in q["results"]} == {"S201-C16", "DS201-C16-30mA-A"}
    rcd = auth.get(
        f"{B}/catalog/products/",
        {"category": "rcd", "leakage_ma": 30, "rcd_type": "A", "poles": 4, "rated_a": 40},
    ).json()
    assert rcd["count"] == 6
    rng = auth.get(f"{B}/catalog/products/", {"category": "mcb", "rated_a_min": 25}).json()
    assert all(float(p["rated_a"]) >= 25 for p in rng["results"])


def test_catalog_pagination(auth, seeded):
    page1 = auth.get(f"{B}/catalog/products/", {"page_size": 20}).json()
    assert len(page1["results"]) == 20 and page1["next"]
    assert auth.get(f"{B}/catalog/products/", {"page_size": 100000}).json()["count"] > 150


def test_brands_and_categories(auth, seeded):
    assert len(auth.get(f"{B}/catalog/brands/").json()) >= 6
    assert any(c["code"] == "mcb" for c in auth.get(f"{B}/catalog/categories/").json())


def test_analogs_endpoint(auth, seeded):
    p = Product.objects.get(brand__name="ABB", sku="S201-C16")
    all_ = auth.get(f"{B}/catalog/products/{p.pk}/analogs/").json()
    prices = [float(a["price"]) for a in all_]
    assert len(all_) == 5 and prices == sorted(prices)
    eco = auth.get(f"{B}/catalog/products/{p.pk}/analogs/", {"tier": "eco"}).json()
    assert {a["brand"]["name"] for a in eco} == {"IEK", "E.NEXT"}
    assert auth.get(f"{B}/catalog/products/{p.pk}/analogs/", {"tier": "gold"}).status_code == 400


def test_catalog_csv_admin_only(auth, seeded, client, django_user_model):
    assert auth.get(f"{B}/catalog/export/").status_code == 403
    assert auth.post(f"{B}/catalog/import/", {}).status_code == 403
    admin = django_user_model.objects.create_superuser(email="adm@example.com", password="x-12345!")
    client.force_authenticate(admin)
    exp = client.get(f"{B}/catalog/export/")
    assert exp.status_code == 200 and exp["Content-Type"].startswith("text/csv")
    from django.core.files.uploadedfile import SimpleUploadedFile

    csv = "brand,category,sku,name,price\nABB,mcb,API-1,Imported,10\n"
    r = client.post(f"{B}/catalog/import/", {"file": SimpleUploadedFile("c.csv", csv.encode())})
    assert r.status_code == 200 and r.json()["created"] == 1
    bad = "brand,category,sku,name,price\nABB,zzz,API-2,Bad,10\n"
    r = client.post(f"{B}/catalog/import/", {"file": SimpleUploadedFile("c.csv", bad.encode())})
    assert r.status_code == 400 and r.json()["errors"]
    assert client.post(f"{B}/catalog/import/", {}).status_code == 400
