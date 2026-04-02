import logging
import time
from threading import Lock

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.http import HttpResponseBadRequest
from django.http.request import split_domain_port, validate_host

from shorty.models import Domain


logger = logging.getLogger('shorty')


class DynamicAllowedHostsMiddleware:
    _cache_lock = Lock()
    _cached_hosts = ()
    _cache_expires_at = 0.0

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_host = request._get_raw_host()
        domain, _port = split_domain_port(raw_host)
        if not domain:
            return HttpResponseBadRequest('Invalid Host header.')

        allowed_hosts = self.get_allowed_hosts()
        if not validate_host(domain, allowed_hosts):
            return HttpResponseBadRequest('Invalid Host header.')

        return self.get_response(request)

    @classmethod
    def get_allowed_hosts(cls):
        static_hosts = list(dict.fromkeys(getattr(settings, 'STATIC_ALLOWED_HOSTS', settings.ALLOWED_HOSTS)))
        if not getattr(settings, 'DYNAMIC_ALLOWED_HOSTS', False):
            return static_hosts

        return list(dict.fromkeys(static_hosts + list(cls.get_cached_domain_hosts())))

    @classmethod
    def get_cached_domain_hosts(cls):
        ttl = max(0, int(getattr(settings, 'DYNAMIC_ALLOWED_HOSTS_CACHE_SECONDS', 5)))
        now = time.monotonic()

        with cls._cache_lock:
            if now < cls._cache_expires_at:
                return cls._cached_hosts

            try:
                hosts = tuple(
                    Domain.objects.filter(host_allowed=True)
                    .values_list('name', flat=True)
                    .order_by('name')
                )
            except (OperationalError, ProgrammingError) as exc:
                logger.warning('Could not load host_allowed domains during request validation: %s', exc)
                hosts = ()

            cls._cached_hosts = hosts
            cls._cache_expires_at = now + ttl
            return cls._cached_hosts
