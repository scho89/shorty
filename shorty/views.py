from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from shorty.models import ClickEvent, Surl

import logging

logger = logging.getLogger('shorty')
CLICK_EVENT_RETENTION_DAYS = getattr(settings, 'CLICK_EVENT_RETENTION_DAYS', 14)
CLICK_EVENT_CLEANUP_CACHE_KEY = 'shorty:click-event-cleanup'


def get_browser_label(user_agent):
    user_agent = (user_agent or '').lower()
    if not user_agent:
        return 'Unknown'
    if 'edg/' in user_agent:
        return 'Edge'
    if 'chrome/' in user_agent and 'edg/' not in user_agent:
        return 'Chrome'
    if 'safari/' in user_agent and 'chrome/' not in user_agent:
        return 'Safari'
    if 'firefox/' in user_agent:
        return 'Firefox'
    if 'trident/' in user_agent or 'msie' in user_agent:
        return 'Internet Explorer'
    if 'android' in user_agent:
        return 'Android Browser'
    return 'Other'


def normalize_referrer_path(referrer):
    referrer = (referrer or '').strip()
    if not referrer:
        return ''

    try:
        parsed = urlparse(referrer)
    except ValueError:
        return ''

    hostname = (parsed.hostname or '').lower()
    if not hostname:
        return ''

    path = parsed.path or ''
    if path == '/':
        path = ''
    return f'{hostname}{path}'


def cleanup_expired_click_events():
    if CLICK_EVENT_RETENTION_DAYS <= 0:
        return

    if not cache.add(CLICK_EVENT_CLEANUP_CACHE_KEY, '1', timeout=3600):
        return

    cutoff = timezone.now() - timezone.timedelta(days=CLICK_EVENT_RETENTION_DAYS)
    ClickEvent.objects.filter(created_at__lt=cutoff).delete()

# Create your views here.


def index(request):
    return redirect('common:url')
    
    # # if request.method == "GET":
    # if request.user.is_authenticated:
    #     surls = Surl.objects.filter(owner__username=request.user.username)
    #     context = {'surls':surls}
    #     return render(request,'shorty/index.html',context=context)    

    # else:
    #     return render(request,'shorty/index.html')    

def surl(request,alias):
    domain = request.get_host().split(':')[0]

    try:
        surl = Surl.objects.only('id', 'url', 'is_active', 'expires_at').get(domain__name=domain, alias=alias)
    except Surl.DoesNotExist:
        return redirect('common:url')

    if not surl.is_active:
        return render(
            request,
            'common/error.html',
            {'err': {'code': 403, 'message': 'This short link is currently disabled.'}},
            status=403,
        )

    if surl.is_expired:
        return render(
            request,
            'common/error.html',
            {'err': {'code': 410, 'message': 'This short link has expired.'}},
            status=410,
        )

    cleanup_expired_click_events()
    Surl.objects.filter(pk=surl.pk).update(visit_counts=F('visit_counts') + 1)
    ClickEvent.objects.create(
        surl_id=surl.pk,
        referrer=normalize_referrer_path(request.META.get('HTTP_REFERER'))[:2048],
        browser=get_browser_label(request.META.get('HTTP_USER_AGENT')),
    )
    return redirect(surl.url)
