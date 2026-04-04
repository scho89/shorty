from django.contrib import admin
from .models import ClickEvent, Surl, Domain

# Register your models here.

class SurlAdmin(admin.ModelAdmin):
    search_fields = ['alias','url','note','domain__name']
    list_display = ('alias','domain','short_url','url','is_active','expires_at','visit_counts')
    
admin.site.register(Surl, SurlAdmin)

class DomainAdmin(admin.ModelAdmin):
    search_fields = ['name','owner__username']
    list_display = ['name','owner']
    
admin.site.register(Domain, DomainAdmin)


class ClickEventAdmin(admin.ModelAdmin):
    search_fields = ['surl__alias', 'surl__domain__name', 'referrer', 'browser']
    list_display = ('surl', 'browser', 'referrer', 'created_at')
    list_filter = ('browser', 'created_at')


admin.site.register(ClickEvent, ClickEventAdmin)
