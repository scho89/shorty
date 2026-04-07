from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.core.cache import cache
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.views import (
    EMAIL_CHANGE_CODE_PREFIX,
    PASSWORD_RESET_CODE_PREFIX,
    build_verification_cache_key,
    get_url_wc_data,
)
from shorty.models import ClickEvent, Domain, FallbackDestination, GlobalRoutingSettings, Surl


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class UrlPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pw12345!')
        self.other_user = User.objects.create_user(username='other', password='pw12345!')
        self.owner_domain = Domain.objects.create(
            name='owner.example.com',
            owner=self.owner,
            is_verified=True,
        )
        self.other_domain = Domain.objects.create(
            name='other.example.com',
            owner=self.other_user,
            is_verified=True,
        )

    def test_cannot_create_short_url_with_someone_elses_domain(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'domain': self.other_domain.pk,
                'alias': 'stolen',
                'url': 'https://example.org/resource',
                'note': 'should fail',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Surl.objects.filter(alias='stolen').exists())

    def test_url_delete_requires_post(self):
        self.client.force_login(self.owner)
        surl = Surl.objects.create(
            alias='demo',
            url='https://example.org/demo',
            note='demo',
            domain=self.owner_domain,
            short_url='owner.example.com/demo',
        )

        response = self.client.get(reverse('common:url_delete', kwargs={'pk': surl.pk}))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Surl.objects.filter(pk=surl.pk).exists())

    def test_cannot_create_short_url_pointing_to_shorty_managed_domain(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'next': reverse('common:links'),
                'active_tab': 'links-create',
                'domain': self.owner_domain.pk,
                'alias': 'loop',
                'url': 'https://owner.example.com/another-alias',
                'note': 'should fail',
                'is_active': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Destination URL cannot point to a Shorty-managed domain.')
        self.assertContains(response, 'id="links-create"')
        self.assertContains(response, 'id="link-form-errors"')
        self.assertFalse(Surl.objects.filter(alias='loop', domain=self.owner_domain).exists())


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class SettingsPageTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='settings-owner', password='pw12345!')
        self.domain = Domain.objects.create(
            name='settings.example.com',
            owner=self.owner,
            is_verified=True,
        )
        self.fallback = FallbackDestination.objects.create(
            name='Company homepage',
            url='https://example.org/fallback/home',
            note='primary fallback',
            owner=self.owner,
        )
        self.other_user = User.objects.create_user(username='settings-other', password='pw12345!')
        self.other_fallback = FallbackDestination.objects.create(
            name='Other homepage',
            url='https://example.org/fallback/other',
            owner=self.other_user,
        )

    def test_settings_page_renders_fallback_registry(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fallback URL registry')
        self.assertContains(response, self.fallback.name)
        self.assertContains(response, 'Save fallback URL')
        self.assertContains(response, 'Workspace routing defaults')
        self.assertContains(response, 'data-open-global-quick-create')
        self.assertContains(response, 'name="mode" value="global_quick"')
        self.assertContains(response, 'data-tab-target="settings-routing"')
        self.assertContains(response, 'data-tab-target="settings-fallback-urls"')
        self.assertNotContains(response, 'data-tab-target="settings-root"')

    def test_global_quick_create_invalid_submission_returns_to_same_page_with_errors(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'mode': 'global_quick',
                'next': reverse('common:settings'),
                'domain': self.domain.pk,
                'alias': 'loop',
                'url': 'https://settings.example.com/loop',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request['PATH_INFO'], reverse('common:settings'))
        self.assertContains(response, 'Destination URL cannot point to a Shorty-managed domain.')
        self.assertContains(response, 'data-global-quick-create-open="true"')
        self.assertContains(response, 'id="global-quick-create-errors"')

    def test_settings_page_creates_fallback_url(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:fallback_destination_create'),
            {
                'name': 'Campaign landing',
                'url': 'https://example.org/fallback/campaign',
                'note': 'campaign backup',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(FallbackDestination.objects.filter(owner=self.owner, name='Campaign landing').exists())

    def test_settings_page_rejects_fallback_url_pointing_to_shorty_managed_domain(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:fallback_destination_create'),
            {
                'name': 'Loop fallback',
                'url': 'https://settings.example.com/missing',
                'note': 'should fail',
                'active_tab': 'settings-fallback-urls',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fallback URL cannot point to a Shorty-managed domain.')
        self.assertFalse(FallbackDestination.objects.filter(owner=self.owner, name='Loop fallback').exists())

    def test_settings_page_redirect_preserves_active_tab(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:fallback_destination_create'),
            {
                'name': 'Campaign landing',
                'url': 'https://example.org/fallback/campaign',
                'note': 'campaign backup',
                'active_tab': 'settings-fallback-urls',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('common:settings')}?tab=settings-fallback-urls")

    def test_domain_settings_page_updates_domain_fallbacks(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_settings_update', kwargs={'pk': self.domain.pk}),
            {
                'root_action': Domain.ROOT_ACTION_FALLBACK,
                'root_fallback': str(self.fallback.pk),
                'root_message': '',
                'missing_alias_action': Domain.ROOT_ACTION_FALLBACK,
                'missing_alias_fallback': str(self.fallback.pk),
                'missing_alias_message': '',
                'inactive_action': Domain.ROOT_ACTION_FALLBACK,
                'inactive_fallback': str(self.fallback.pk),
                'inactive_message': '',
                'expired_action': Domain.ROOT_ACTION_FALLBACK,
                'expired_fallback': str(self.fallback.pk),
                'expired_message': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.domain.refresh_from_db()
        self.assertEqual(self.domain.root_action, Domain.ROOT_ACTION_FALLBACK)
        self.assertEqual(self.domain.root_fallback, self.fallback)
        self.assertEqual(self.domain.missing_alias_action, Domain.ROOT_ACTION_FALLBACK)
        self.assertEqual(self.domain.missing_alias_fallback, self.fallback)
        self.assertEqual(self.domain.expired_fallback, self.fallback)

    def test_domain_settings_redirect_preserves_active_tab(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_settings_update', kwargs={'pk': self.domain.pk}),
            {
                'root_action': Domain.POLICY_ACTION_INHERIT,
                'root_fallback': '',
                'root_message': '',
                'missing_alias_action': Domain.POLICY_ACTION_INHERIT,
                'missing_alias_fallback': '',
                'missing_alias_message': '',
                'inactive_action': Domain.POLICY_ACTION_INHERIT,
                'inactive_fallback': '',
                'inactive_message': '',
                'expired_action': Domain.ROOT_ACTION_FALLBACK,
                'expired_fallback': str(self.fallback.pk),
                'expired_message': '',
                'active_tab': 'domain-expired',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('common:domain_settings', kwargs={'pk': self.domain.pk})}?tab=domain-expired",
        )

    def test_domain_settings_rejects_other_workspace_fallback(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_settings_update', kwargs={'pk': self.domain.pk}),
            {
                'root_action': Domain.POLICY_ACTION_INHERIT,
                'root_fallback': '',
                'root_message': '',
                'missing_alias_action': Domain.ROOT_ACTION_FALLBACK,
                'missing_alias_fallback': str(self.other_fallback.pk),
                'missing_alias_message': '',
                'inactive_action': Domain.POLICY_ACTION_INHERIT,
                'inactive_fallback': '',
                'inactive_message': '',
                'expired_action': Domain.POLICY_ACTION_INHERIT,
                'expired_fallback': '',
                'expired_message': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.domain.name)
        self.domain.refresh_from_db()
        self.assertIsNone(self.domain.missing_alias_fallback)

    def test_settings_page_updates_global_defaults(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:global_routing_settings_update'),
            {
                'root_action': Domain.ROOT_ACTION_FALLBACK,
                'root_fallback': str(self.fallback.pk),
                'root_message': '',
                'missing_alias_action': Domain.MESSAGE_ACTION,
                'missing_alias_fallback': '',
                'missing_alias_message': 'Global missing copy',
                'inactive_action': Domain.MESSAGE_ACTION,
                'inactive_fallback': '',
                'inactive_message': 'Global inactive copy',
                'expired_action': Domain.ROOT_ACTION_FALLBACK,
                'expired_fallback': str(self.fallback.pk),
                'expired_message': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        global_settings = GlobalRoutingSettings.objects.get(owner=self.owner)
        self.assertEqual(global_settings.root_action, Domain.ROOT_ACTION_FALLBACK)
        self.assertEqual(global_settings.root_fallback, self.fallback)
        self.assertEqual(global_settings.missing_alias_action, Domain.MESSAGE_ACTION)
        self.assertEqual(global_settings.missing_alias_message, 'Global missing copy')

    def test_domain_list_links_rows_to_domain_settings(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:domain_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-href="{reverse("common:domain_settings", kwargs={"pk": self.domain.pk})}"')
        self.assertNotContains(response, 'Delete domain')
        self.assertContains(response, 'data-tab-target="domains-library"')
        self.assertContains(response, 'data-tab-target="domains-create"')
        self.assertNotContains(response, '<th>Routing</th>', html=False)

    def test_domain_create_redirect_preserves_active_tab(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_create'),
            {
                'name': 'new-settings.example.com',
                'active_tab': 'domains-create',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('common:domain_list')}?tab=domains-create")

    def test_domain_settings_page_shows_verify_and_delete_actions(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:domain_settings', kwargs={'pk': self.domain.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete domain')
        self.assertContains(response, 'Domain verified')
        self.assertContains(response, 'data-tab-target="domain-overview"')
        self.assertContains(response, 'data-tab-target="domain-routing"')
        self.assertNotContains(response, 'data-tab-target="domain-root"')


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class WordCloudTests(TestCase):
    def test_word_cloud_handles_zero_visit_counts(self):
        owner = User.objects.create_user(username='wc-user', password='pw12345!')
        domain = Domain.objects.create(name='wc.example.com', owner=owner, is_verified=True)
        Surl.objects.create(
            alias='zero',
            url='https://example.org/zero',
            note='zero count',
            domain=domain,
            short_url='wc.example.com/zero',
            visit_counts=0,
        )

        wc_data, colors = get_url_wc_data(Surl.objects.filter(domain=domain))

        self.assertEqual(len(wc_data), 1)
        self.assertGreaterEqual(wc_data[0]['weight'], 1)
        self.assertEqual(len(colors), 0)


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class UrlInsightsViewsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='stats-owner', password='pw12345!')
        self.other_user = User.objects.create_user(username='stats-other', password='pw12345!')
        self.domain = Domain.objects.create(
            name='stats.example.com',
            owner=self.owner,
            is_verified=True,
        )
        self.surl = Surl.objects.create(
            alias='launch',
            url='https://example.org/launch',
            note='campaign launch',
            domain=self.domain,
            short_url='stats.example.com/launch',
            expires_at=timezone.now() + timedelta(days=7),
        )
        ClickEvent.objects.create(surl=self.surl, referrer='news.example.com/story', browser='Chrome')
        ClickEvent.objects.create(surl=self.surl, referrer='', browser='Safari')

    def test_stats_view_requires_link_ownership(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse('common:url_stats', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 404)

    def test_stats_view_renders_click_breakdown(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url_stats', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'campaign launch')
        self.assertContains(response, 'news.example.com')
        self.assertContains(response, 'Chrome')

    def test_qr_code_view_returns_svg(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url_qr_code', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')
        self.assertContains(response, '<svg', status_code=200)

    def test_stats_view_includes_qr_preview_image(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url_stats', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('common:url_qr_code', kwargs={'pk': self.surl.pk}))
        self.assertContains(response, 'alt="QR code for')

    def test_stats_toggle_active_updates_link_state(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_toggle_active', kwargs={'pk': self.surl.pk}),
            {'next': reverse('common:url_stats', kwargs={'pk': self.surl.pk})},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.surl.refresh_from_db()
        self.assertFalse(self.surl.is_active)

    def test_dashboard_cards_link_to_stats_page(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('common:url_stats', kwargs={'pk': self.surl.pk}))
        self.assertNotContains(response, f'href="{self.surl.url}"')

    def test_links_page_routes_to_detail_view(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:links'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-href="{reverse("common:url_stats", kwargs={"pk": self.surl.pk})}"')
        self.assertContains(response, reverse('common:url_stats', kwargs={'pk': self.surl.pk}))
        self.assertContains(response, 'data-tab-target="links-library"')
        self.assertContains(response, 'data-tab-target="links-create"')

    def test_links_page_shows_created_notice_with_detail_button(self):
        self.client.force_login(self.owner)

        response = self.client.get(f"{reverse('common:links')}?created={self.surl.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Link created')
        self.assertContains(response, reverse('common:url_stats', kwargs={'pk': self.surl.pk}))
        self.assertContains(response, 'data-open-global-quick-create')


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class QuickCreateTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='quick-owner', password='pw12345!')
        self.domain = Domain.objects.create(
            name='quick.example.com',
            owner=self.owner,
            is_verified=True,
        )

    def test_dashboard_quick_create_generates_alias_and_redirects_to_stats(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'mode': 'quick',
                'next': reverse('common:url'),
                'domain': self.domain.pk,
                'url': 'https://example.org/quick-start',
                'alias': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created = Surl.objects.get(domain=self.domain)
        self.assertTrue(created.alias)
        self.assertTrue(created.is_active)
        self.assertRedirects(response, f"{reverse('common:url')}?created={created.pk}")
        self.assertContains(response, created.short_url)
        self.assertContains(response, 'Open details')

    def test_links_create_generates_alias_when_blank(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'next': reverse('common:links'),
                'domain': self.domain.pk,
                'url': 'https://example.org/library-create',
                'alias': '',
                'note': 'created from links',
                'is_active': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created = Surl.objects.get(url='https://example.org/library-create')
        self.assertTrue(created.alias)
        self.assertTrue(created.is_active)

    def test_links_create_redirect_preserves_active_tab(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:url_create'),
            {
                'next': reverse('common:links'),
                'active_tab': 'links-create',
                'domain': self.domain.pk,
                'url': 'https://example.org/library-create-two',
                'alias': '',
                'note': 'created from links tab',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, reverse('common:links'))
        self.assertEqual(query.get('tab'), ['links-create'])
        self.assertEqual(len(query.get('created', [])), 1)


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class AuthRecaptchaTests(TestCase):
    @override_settings(DEBUG=True, RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET='')
    def test_signup_allows_debug_flow_without_recaptcha(self):
        response = self.client.post(
            reverse('common:signup'),
            {
                'username': 'debug-user',
                'password1': 'ComplexPass123!',
                'password2': 'ComplexPass123!',
                'email': 'debug@example.com',
                'privacy_consent': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='debug-user').exists())

    @override_settings(DEBUG=True, RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET='')
    def test_signup_requires_privacy_consent(self):
        response = self.client.post(
            reverse('common:signup'),
            {
                'username': 'debug-user-no-consent',
                'password1': 'ComplexPass123!',
                'password2': 'ComplexPass123!',
                'email': 'debug@example.com',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='debug-user-no-consent').exists())
        self.assertContains(response, 'You must agree to the privacy notice')

    @override_settings(DEBUG=True, RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET='')
    def test_signup_page_shows_usage_log_notice(self):
        response = self.client.get(reverse('common:signup'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'host name with page path')
        self.assertContains(response, 'retained for 14 days')

    @override_settings(DEBUG=True, RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET='')
    def test_login_allows_debug_flow_without_recaptcha(self):
        user = User.objects.create_user(username='debug-login', password='ComplexPass123!')

        response = self.client.post(
            reverse('common:login'),
            {
                'username': user.username,
                'password': 'ComplexPass123!',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class AccountSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='account-user',
            password='ComplexPass123!',
            email='before@example.com',
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_account_settings_updates_email_after_verification(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('common:account_settings'),
            {
                'action': 'email_request',
                'new_email': 'after@example.com',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payload = cache.get(build_verification_cache_key(EMAIL_CHANGE_CODE_PREFIX, self.user.pk))
        self.assertIsNotNone(payload)
        self.assertEqual(payload['email'], 'after@example.com')
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(
            reverse('common:account_settings'),
            {
                'action': 'email_verify',
                'email_verify-verification_code': payload['code'],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'after@example.com')

    def test_password_change_uses_django_builtin_form_on_account_page(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('common:account_settings'),
            {
                'action': 'password',
                'password-old_password': 'ComplexPass123!',
                'password-new_password1': 'EvenBetterPass456!',
                'password-new_password2': 'EvenBetterPass456!',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('EvenBetterPass456!'))


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='reset-user',
            password='ComplexPass123!',
            email='reset@example.com',
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_uses_email_verification_code(self):
        response = self.client.post(
            reverse('common:password_reset_request'),
            {
                'email': 'reset@example.com',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        payload = cache.get(build_verification_cache_key(PASSWORD_RESET_CODE_PREFIX, 'reset@example.com'))
        self.assertIsNotNone(payload)

        response = self.client.post(
            reverse('common:password_reset_verify'),
            {
                'verification_code': payload['code'],
                'new_password1': 'NewComplexPass456!',
                'new_password2': 'NewComplexPass456!',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewComplexPass456!'))


@override_settings(
    ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    STATIC_ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'],
    DYNAMIC_ALLOWED_HOSTS=False,
)
class UsernameReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reminder-user',
            password='ComplexPass123!',
            email='reminder@example.com',
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_username_reminder_sends_username_by_email(self):
        response = self.client.post(
            reverse('common:username_reminder_request'),
            {
                'email': 'reminder@example.com',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('reminder-user', mail.outbox[0].body)
