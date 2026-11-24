import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from projects.models import ConsumerGroup, Panel, PanelLink, Project


@pytest.fixture
def project(user):
    return Project.objects.create(owner=user, name="Квартира")


def test_owner_isolation(user, other_user, project):
    assert list(Project.objects.for_user(user)) == [project]
    assert list(Project.objects.for_user(other_user)) == []


def test_panel_name_unique_per_project(project):
    Panel.objects.create(project=project, name="ГРЩ")
    with pytest.raises(IntegrityError):
        Panel.objects.create(project=project, name="ГРЩ")


def test_panel_link_cycle_and_self(project):
    a = Panel.objects.create(project=project, name="A")
    b = Panel.objects.create(project=project, name="B")
    c = Panel.objects.create(project=project, name="C")
    PanelLink.objects.create(source=a, target=b)
    PanelLink.objects.create(source=b, target=c)
    with pytest.raises(ValidationError):
        PanelLink(source=c, target=a).save()  # cycle
    with pytest.raises(ValidationError):
        PanelLink(source=a, target=a).save()  # self


def test_panel_single_feeder(project):
    a = Panel.objects.create(project=project, name="A")
    b = Panel.objects.create(project=project, name="B")
    c = Panel.objects.create(project=project, name="C")
    PanelLink.objects.create(source=a, target=c)
    with pytest.raises(ValidationError):
        PanelLink(source=b, target=c).save()


def test_panel_link_cross_project(user, project):
    other = Project.objects.create(owner=user, name="Дом")
    a = Panel.objects.create(project=project, name="A")
    b = Panel.objects.create(project=other, name="B")
    with pytest.raises(ValidationError):
        PanelLink(source=a, target=b).save()


def test_group_constraints(project):
    with pytest.raises(IntegrityError):
        ConsumerGroup.objects.create(project=project, name="x", power_w=0)


def test_group_panel_same_project(user, project):
    other = Project.objects.create(owner=user, name="Дом")
    p = Panel.objects.create(project=other, name="P")
    g = ConsumerGroup(project=project, name="g", power_w=100, panel=p)
    with pytest.raises(ValidationError):
        g.full_clean()


def test_project_cascade_delete(project):
    Panel.objects.create(project=project, name="A")
    ConsumerGroup.objects.create(project=project, name="g", power_w=100)
    project.delete()
    assert Panel.objects.count() == 0 and ConsumerGroup.objects.count() == 0
