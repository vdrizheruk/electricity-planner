import pytest
from rest_framework.test import APIClient

from catalog.models import Product
from panels.models import DinRail
from projects.models import Panel, Project

PW = "S3cure-pass-77!"


@pytest.fixture
def client(db):
    return APIClient()


@pytest.fixture
def auth(client, user):
    client.force_authenticate(user)
    return client


@pytest.fixture
def other_client(other_user):
    c = APIClient()
    c.force_authenticate(other_user)
    return c


@pytest.fixture
def project(user):
    return Project.objects.create(owner=user, name="Квартира", main_breaker_a=63)


@pytest.fixture
def enclosure(seeded):
    # Hager flush 24 modules: 2 rows x 12, 250 x 340 mm
    return Product.objects.get(brand__name="Hager", sku="VF-24")


@pytest.fixture
def panel(project, enclosure):
    p = Panel.objects.create(project=project, name="ГРЩ", enclosure=enclosure)
    from panels.layout_db import sync_rails

    sync_rails(p)
    return p


@pytest.fixture
def rails(panel):
    return list(DinRail.objects.filter(panel=panel).order_by("row_index"))


@pytest.fixture
def mcb(seeded):
    return Product.objects.get(brand__name="ABB", sku="S201-C16")  # 1 module


@pytest.fixture
def mcb3(seeded):
    return Product.objects.get(brand__name="ABB", sku="S203-C32")  # 3 modules


@pytest.fixture
def contactor(seeded):
    return Product.objects.get(brand__name="Eaton", sku="DILM40-10")  # not DIN
