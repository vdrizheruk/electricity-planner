def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz(client, db):
    assert client.get("/readyz").status_code == 200


def test_user_email_login_model(django_user_model, db):
    u = django_user_model.objects.create_superuser(email="root@example.com", password="x-12345!")
    assert u.is_staff and u.is_superuser and u.USERNAME_FIELD == "email"
    with __import__("pytest").raises(ValueError):
        django_user_model.objects.create_user(email="", password="x")
