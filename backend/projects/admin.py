from django.contrib import admin

from .models import ConsumerGroup, Panel, PanelLink, Project

admin.site.register([Project, Panel, PanelLink, ConsumerGroup])
