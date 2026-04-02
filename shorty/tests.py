from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shorty.models import Domain, Surl


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
        )

        surl.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.org/fast')
        self.assertEqual(surl.visit_counts, 1)


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
