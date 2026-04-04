from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shorty.models import ClickEvent, Domain, Surl


class DomainVerificationTests(TestCase):
    def test_recent_verification_attempt_returns_retry_without_dns_lookup(self):
        owner = User.objects.create_user(username='verifier', password='pw12345!')
        domain = Domain.objects.create(
            name='recent-check.example.com',
            owner=owner,
            dns_txt='shorty-test-token',
            last_ownership_check=timezone.now(),
        )

        with patch('shorty.models.resolve') as mock_resolve:
            result = domain.verify_ownership()

        self.assertEqual(result, 1)
        mock_resolve.assert_not_called()


class RedirectTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_redirect_increments_visit_count_and_redirects(self):
        owner = User.objects.create_user(username='redirect-owner', password='pw12345!')
        domain = Domain.objects.create(name='redirect.example.com', owner=owner, is_verified=True)
        surl = Surl.objects.create(
            alias='fast',
            url='https://example.org/fast',
            note='speed test',
            domain=domain,
            short_url='redirect.example.com/fast',
            visit_counts=0,
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'fast'}),
            HTTP_HOST='redirect.example.com',
            HTTP_REFERER='https://referrer.example.com/article',
            HTTP_USER_AGENT='Mozilla/5.0 Chrome/123.0',
        )

        surl.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fast')
        self.assertEqual(surl.visit_counts, 1)
        event = ClickEvent.objects.get(surl=surl)
        self.assertEqual(event.referrer, 'referrer.example.com/article')
        self.assertEqual(event.browser, 'Chrome')

    @override_settings(CLICK_EVENT_RETENTION_DAYS=14)
    def test_redirect_cleans_up_old_click_events(self):
        owner = User.objects.create_user(username='cleanup-owner', password='pw12345!')
        domain = Domain.objects.create(name='cleanup.example.com', owner=owner, is_verified=True)
        surl = Surl.objects.create(
            alias='fresh',
            url='https://example.org/fresh',
            note='cleanup test',
            domain=domain,
            short_url='cleanup.example.com/fresh',
        )
        old_event = ClickEvent.objects.create(surl=surl, referrer='old.example.com', browser='Chrome')
        ClickEvent.objects.filter(pk=old_event.pk).update(
            created_at=timezone.now() - timedelta(days=15)
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'fresh'}),
            HTTP_HOST='cleanup.example.com',
            HTTP_REFERER='https://new.example.com/path?q=1',
            HTTP_USER_AGENT='Mozilla/5.0 Chrome/123.0',
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClickEvent.objects.filter(pk=old_event.pk).exists())
        self.assertTrue(ClickEvent.objects.filter(surl=surl, referrer='new.example.com/path').exists())

    def test_disabled_link_returns_403_without_tracking(self):
        owner = User.objects.create_user(username='disabled-owner', password='pw12345!')
        domain = Domain.objects.create(name='disabled.example.com', owner=owner, is_verified=True)
        surl = Surl.objects.create(
            alias='off',
            url='https://example.org/off',
            note='disabled link',
            domain=domain,
            short_url='disabled.example.com/off',
            is_active=False,
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'off'}),
            HTTP_HOST='disabled.example.com',
        )

        surl.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(surl.visit_counts, 0)
        self.assertFalse(ClickEvent.objects.filter(surl=surl).exists())

    def test_expired_link_returns_410_without_tracking(self):
        owner = User.objects.create_user(username='expired-owner', password='pw12345!')
        domain = Domain.objects.create(name='expired.example.com', owner=owner, is_verified=True)
        surl = Surl.objects.create(
            alias='gone',
            url='https://example.org/gone',
            note='expired link',
            domain=domain,
            short_url='expired.example.com/gone',
            expires_at=timezone.now() - timedelta(minutes=5),
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'gone'}),
            HTTP_HOST='expired.example.com',
        )

        surl.refresh_from_db()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(surl.visit_counts, 0)
        self.assertFalse(ClickEvent.objects.filter(surl=surl).exists())


class CaddyAskTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='caddy-owner', password='pw12345!')

    def test_caddy_ask_allows_host_allowed_domain(self):
        Domain.objects.create(
            name='allowed.example.com',
            owner=self.owner,
            is_verified=True,
            host_allowed=True,
        )

        response = self.client.get('/_caddy/ask', {'domain': 'allowed.example.com'})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'status': 'ok', 'domain': 'allowed.example.com'})

    def test_caddy_ask_denies_unapproved_domain(self):
        Domain.objects.create(
            name='blocked.example.com',
            owner=self.owner,
            is_verified=True,
            host_allowed=False,
        )

        response = self.client.get('/_caddy/ask', {'domain': 'blocked.example.com'})

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {'status': 'denied', 'domain': 'blocked.example.com'})

    def test_caddy_ask_requires_domain_query_param(self):
        response = self.client.get('/_caddy/ask')

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {'status': 'denied', 'reason': 'missing domain'})


class DynamicAllowedHostsTests(TestCase):
    @override_settings(
        ALLOWED_HOSTS=['*'],
        STATIC_ALLOWED_HOSTS=['shorty.example.com'],
        DYNAMIC_ALLOWED_HOSTS=True,
        DYNAMIC_ALLOWED_HOSTS_CACHE_SECONDS=0,
    )
    def test_dynamic_host_allowed_domain_works_without_restart(self):
        owner = User.objects.create_user(username='dynamic-owner', password='pw12345!')
        domain = Domain.objects.create(
            name='dynamic.example.com',
            owner=owner,
            is_verified=True,
            host_allowed=True,
        )
        surl = Surl.objects.create(
            alias='live',
            url='https://example.org/live',
            note='dynamic host',
            domain=domain,
            short_url='dynamic.example.com/live',
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'live'}),
            HTTP_HOST='dynamic.example.com',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/live')

    @override_settings(
        ALLOWED_HOSTS=['*'],
        STATIC_ALLOWED_HOSTS=['shorty.example.com'],
        DYNAMIC_ALLOWED_HOSTS=True,
        DYNAMIC_ALLOWED_HOSTS_CACHE_SECONDS=0,
    )
    def test_dynamic_host_rejects_unknown_domain(self):
        response = self.client.get('/', HTTP_HOST='unknown.example.com')

        self.assertEqual(response.status_code, 400)
