from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from catalog.models import Product


def test_admin_export_import(seeded, client, django_user_model):
    admin = django_user_model.objects.create_superuser(
        email="root@example.com", password="x-12345!"
    )
    client.force_login(admin)
    r = client.get(reverse("admin:catalog_product_export"))
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    assert client.get(reverse("admin:catalog_product_import")).status_code == 200
    csv = "brand,category,sku,name,price\nABB,mcb,ADM-1,Imported,10\n"
    r = client.post(
        reverse("admin:catalog_product_import"),
        {"file": SimpleUploadedFile("c.csv", csv.encode())},
    )
    assert r.status_code == 302
    assert Product.objects.filter(sku="ADM-1").exists()


def test_admin_export_requires_staff(seeded, client, user):
    client.force_login(user)
    assert client.get(reverse("admin:catalog_product_export")).status_code == 302
