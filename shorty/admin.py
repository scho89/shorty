from django.contrib import admin
from .models import Surl, Domain

# Register your models here.

class SurlAdmin(admin.ModelAdmin):
    search_fields = ['alias','url','note','domain__name']
    list_display = ('alias','domain','short_url','url','note')
    
admin.site.register(Surl, SurlAdmin)

class DomainAdmin(admin.ModelAdmin):
    search_fields = ['name','owner__username']
    list_display = ['name','owner']
    
admin.site.register(Domain, DomainAdmin)