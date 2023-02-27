from django.contrib import admin
from .models import Surl, Domain

# Register your models here.

class SurlAdmin(admin.ModelAdmin):
    search_fields = ['alias','url','note']
    list_display = ('alias','domain','short_url','url','note','owner')
    
admin.site.register(Surl, SurlAdmin)

class DomainAdmin(admin.ModelAdmin):
    search_fields = ['name']
    list_display = ['name','owner']
    
admin.site.register(Domain, DomainAdmin)