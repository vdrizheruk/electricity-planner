from django.contrib import admin

from .models import DinRail, LayoutVersion, Placement

admin.site.register([DinRail, Placement, LayoutVersion])
