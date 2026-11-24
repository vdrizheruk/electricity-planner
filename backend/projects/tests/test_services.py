import pytest

from projects.models import ConsumerGroup, Project
from projects.services import autoselect_project


@pytest.fixture
def project(user):
    p = Project.objects.create(owner=user, name="Квартира", main_breaker_a=63)
    for name, t, power, length in (
        ("Свет", "lighting", 800, 25),
        ("Розетки", "sockets", 3000, 20),
        ("Плита", "cooker", 7000, 15),
    ):
        ConsumerGroup.objects.create(project=p, name=name, type=t, power_w=power, length_m=length)
    return p


def test_autoselect_saves_results(project):
    res = autoselect_project(project)
    assert res.ok
    by = {g.name: g for g in project.groups.all()}
    assert (by["Свет"].breaker_a, by["Свет"].curve, float(by["Свет"].cable_mm2)) == (10, "B", 1.5)
    assert (by["Плита"].breaker_a, float(by["Плита"].cable_mm2)) == (32, 4.0)
    assert by["Розетки"].rcd_ma == 30 and by["Свет"].rcd_ma is None
    assert all(g.assigned_phase == "L1" for g in by.values())


def test_autoselect_dry_run_does_not_save(project):
    autoselect_project(project, save=False)
    assert project.groups.filter(breaker_a__isnull=False).count() == 0


def test_autoselect_three_phase(user):
    p = Project.objects.create(owner=user, name="Дом", grid="3ph", main_breaker_a=40)
    for i in range(3):
        ConsumerGroup.objects.create(project=p, name=f"R{i}", type="sockets", power_w=2000)
    res = autoselect_project(p)
    assert res.phases.imbalance_pct == pytest.approx(0.0)
    assert sorted(g.assigned_phase for g in p.groups.all()) == ["L1", "L2", "L3"]
