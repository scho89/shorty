from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shorty.models import ClickEvent, Domain, FallbackDestination, GlobalRoutingSettings, Surl


@override_settings(
    ALLOWED_HOSTS=['*'],
    STATIC_ALLOWED_HOSTS=['*'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
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


@override_settings(
    ALLOWED_HOSTS=['*'],
    STATIC_ALLOWED_HOSTS=['*'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
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

    def test_missing_alias_redirects_to_domain_fallback_url(self):
        owner = User.objects.create_user(username='missing-owner', password='pw12345!')
        domain = Domain.objects.create(name='missing.example.com', owner=owner, is_verified=True)
        fallback = FallbackDestination.objects.create(
            name='Missing alias landing',
            url='https://example.org/fallback/missing',
            owner=owner,
        )
        domain.missing_alias_action = Domain.ROOT_ACTION_FALLBACK
        domain.missing_alias_fallback = fallback
        domain.save(update_fields=['missing_alias_action', 'missing_alias_fallback'])

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'unknown'}),
            HTTP_HOST='missing.example.com',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fallback/missing')

    def test_expired_link_redirects_to_domain_fallback_url(self):
        owner = User.objects.create_user(username='expired-fallback-owner', password='pw12345!')
        domain = Domain.objects.create(name='expired-fallback.example.com', owner=owner, is_verified=True)
        fallback = FallbackDestination.objects.create(
            name='Expired landing',
            url='https://example.org/fallback/expired',
            owner=owner,
        )
        expired = Surl.objects.create(
            alias='old',
            url='https://example.org/old',
            note='expired link',
            domain=domain,
            short_url='expired-fallback.example.com/old',
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        domain.expired_action = Domain.ROOT_ACTION_FALLBACK
        domain.expired_fallback = fallback
        domain.save(update_fields=['expired_action', 'expired_fallback'])

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': expired.alias}),
            HTTP_HOST='expired-fallback.example.com',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fallback/expired')
        self.assertFalse(ClickEvent.objects.filter(surl=expired).exists())

    def test_inactive_link_redirects_to_domain_fallback_url(self):
        owner = User.objects.create_user(username='inactive-fallback-owner', password='pw12345!')
        domain = Domain.objects.create(name='inactive-fallback.example.com', owner=owner, is_verified=True)
        fallback = FallbackDestination.objects.create(
            name='Inactive landing',
            url='https://example.org/fallback/inactive',
            owner=owner,
        )
        inactive = Surl.objects.create(
            alias='paused',
            url='https://example.org/paused',
            note='inactive link',
            domain=domain,
            short_url='inactive-fallback.example.com/paused',
            is_active=False,
        )
        domain.inactive_action = Domain.ROOT_ACTION_FALLBACK
        domain.inactive_fallback = fallback
        domain.save(update_fields=['inactive_action', 'inactive_fallback'])

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': inactive.alias}),
            HTTP_HOST='inactive-fallback.example.com',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fallback/inactive')
        self.assertFalse(ClickEvent.objects.filter(surl=inactive).exists())

    def test_domain_root_redirects_to_configured_fallback_url(self):
        owner = User.objects.create_user(username='root-link-owner', password='pw12345!')
        domain = Domain.objects.create(
            name='root-link.example.com',
            owner=owner,
            is_verified=True,
            root_action=Domain.ROOT_ACTION_FALLBACK,
        )
        fallback = FallbackDestination.objects.create(
            name='Root landing',
            url='https://example.org/fallback/root',
            owner=owner,
        )
        domain.root_fallback = fallback
        domain.save(update_fields=['root_fallback'])

        response = self.client.get('/', HTTP_HOST='root-link.example.com')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fallback/root')

    def test_global_missing_alias_policy_applies_when_domain_inherits(self):
        owner = User.objects.create_user(username='global-owner', password='pw12345!')
        domain = Domain.objects.create(name='global.example.com', owner=owner, is_verified=True)
        fallback = FallbackDestination.objects.create(
            name='Global missing',
            url='https://example.org/fallback/global-missing',
            owner=owner,
        )
        GlobalRoutingSettings.objects.create(
            owner=owner,
            missing_alias_action=Domain.ROOT_ACTION_FALLBACK,
            missing_alias_fallback=fallback,
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'missing'}),
            HTTP_HOST='global.example.com',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fallback/global-missing')

    def test_domain_override_wins_over_global_policy(self):
        owner = User.objects.create_user(username='override-owner', password='pw12345!')
        domain = Domain.objects.create(
            name='override.example.com',
            owner=owner,
            is_verified=True,
            missing_alias_action=Domain.MESSAGE_ACTION,
            missing_alias_message='Domain override copy',
        )
        fallback = FallbackDestination.objects.create(
            name='Global fallback',
            url='https://example.org/fallback/global',
            owner=owner,
        )
        GlobalRoutingSettings.objects.create(
            owner=owner,
            missing_alias_action=Domain.ROOT_ACTION_FALLBACK,
            missing_alias_fallback=fallback,
        )

        response = self.client.get(
            reverse('shorty:alias', kwargs={'alias': 'missing'}),
            HTTP_HOST='override.example.com',
        )

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Domain override copy', status_code=404)


@override_settings(
    ALLOWED_HOSTS=['*'],
    STATIC_ALLOWED_HOSTS=['*'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
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
