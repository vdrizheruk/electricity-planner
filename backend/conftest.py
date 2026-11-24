import pytest
from django.core.management import call_command


@pytest.fixture
def seeded(db):
    call_command("seed_catalog")


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(email="a@example.com", password="pw-12345!")


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(email="b@example.com", password="pw-12345!")
