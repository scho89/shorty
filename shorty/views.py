from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from shorty.models import ClickEvent, Domain, FallbackDestination, GlobalRoutingSettings, Surl

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

DEFAULT_ERROR_MESSAGES = {
    'missing_alias': 'This short link could not be found.',
    'inactive': 'This short link is currently disabled.',
    'expired': 'This short link has expired.',
    'root': 'This branded short link domain is available, but no root destination has been configured yet.',
}


def get_request_domain(request):
    host = request.get_host().split(':')[0]
    return (
        Domain.objects.filter(name__iexact=host)
        .only(
            'id', 'name', 'owner_id',
            'root_action', 'root_fallback_id', 'root_message',
            'missing_alias_action', 'missing_alias_fallback_id', 'missing_alias_message',
            'inactive_action', 'inactive_fallback_id', 'inactive_message',
            'expired_action', 'expired_fallback_id', 'expired_message',
        )
        .first()
    )


def get_global_routing_settings(owner_id):
    if not owner_id:
        return None
    return (
        GlobalRoutingSettings.objects.filter(owner_id=owner_id)
        .only(
            'root_action', 'root_fallback_id', 'root_message',
            'missing_alias_action', 'missing_alias_fallback_id', 'missing_alias_message',
            'inactive_action', 'inactive_fallback_id', 'inactive_message',
            'expired_action', 'expired_fallback_id', 'expired_message',
        )
        .first()
    )


def get_fallback_by_id(owner_id, fallback_id):
    if not fallback_id:
        return None
    return (
        FallbackDestination.objects.only('id', 'url')
        .filter(pk=fallback_id, owner_id=owner_id)
        .first()
    )


def redirect_to_fallback(fallback):
    return redirect(fallback.url)


def resolve_effective_policy(domain, global_settings, policy_name):
    action_field = f'{policy_name}_action'
    fallback_field = f'{policy_name}_fallback'
    message_field = f'{policy_name}_message'

    domain_action = getattr(domain, action_field, Domain.POLICY_ACTION_INHERIT)
    if domain_action and domain_action != Domain.POLICY_ACTION_INHERIT:
        action = domain_action
        fallback_id = getattr(domain, f'{fallback_field}_id', None)
        message = (getattr(domain, message_field, '') or '').strip()
    elif global_settings is not None:
        action = getattr(global_settings, action_field)
        fallback_id = getattr(global_settings, f'{fallback_field}_id', None)
        message = (getattr(global_settings, message_field, '') or '').strip()
    else:
        if policy_name == 'root':
            action = Domain.ROOT_ACTION_DASHBOARD
        else:
            action = Domain.MESSAGE_ACTION
        fallback_id = None
        message = ''

    return {
        'action': action,
        'fallback': get_fallback_by_id(domain.owner_id, fallback_id),
        'message': message,
    }


def render_domain_error(request, domain, *, status_code, message):
    return render(
        request,
        'common/error.html',
        {
            'err': {
                'code': status_code,
                'message': message,
                'button_href': domain.get_absolute_url() if domain else '/',
                'button_label': 'Open domain root' if domain else 'Go home',
            }
        },
        status=status_code,
    )


def handle_domain_root(request, domain):
    if not domain:
        return redirect('common:url')

    global_settings = get_global_routing_settings(domain.owner_id)
    policy = resolve_effective_policy(domain, global_settings, 'root')

    if policy['action'] == Domain.ROOT_ACTION_FALLBACK and policy['fallback']:
        return redirect_to_fallback(policy['fallback'])

    if policy['action'] in {Domain.MESSAGE_ACTION, Domain.ROOT_ACTION_SHOW_MESSAGE}:
        message = policy['message'] or DEFAULT_ERROR_MESSAGES['root']
        return render_domain_error(request, domain, status_code=200, message=message)

    return redirect('common:url')


def handle_domain_policy(request, domain, *, message_type, status_code):
    global_settings = get_global_routing_settings(domain.owner_id)
    policy = resolve_effective_policy(domain, global_settings, message_type)
    if policy['action'] == Domain.ROOT_ACTION_FALLBACK and policy['fallback']:
        return redirect_to_fallback(policy['fallback'])
    message = policy['message'] or DEFAULT_ERROR_MESSAGES[message_type]
    return render_domain_error(request, domain, status_code=status_code, message=message)


def index(request):
    domain = get_request_domain(request)
    return handle_domain_root(request, domain)


def surl(request,alias):
    domain = get_request_domain(request)
    if not domain:
        return redirect('common:url')

    try:
        surl = Surl.objects.only('id', 'url', 'is_active', 'expires_at').get(domain=domain, alias=alias)
    except Surl.DoesNotExist:
        return handle_domain_policy(
            request,
            domain,
            message_type='missing_alias',
            status_code=404,
        )

    if not surl.is_active:
        return handle_domain_policy(
            request,
            domain,
            message_type='inactive',
            status_code=403,
        )

    if surl.is_expired:
        return handle_domain_policy(
            request,
            domain,
            message_type='expired',
            status_code=410,
        )

    cleanup_expired_click_events()
    Surl.objects.filter(pk=surl.pk).update(visit_counts=F('visit_counts') + 1)
    ClickEvent.objects.create(
        surl_id=surl.pk,
        referrer=normalize_referrer_path(request.META.get('HTTP_REFERER'))[:2048],
        browser=get_browser_label(request.META.get('HTTP_USER_AGENT')),
    )
    return redirect(surl.url)
