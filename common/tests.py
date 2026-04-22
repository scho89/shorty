from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

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
        self.assertContains(response, 'data-short-url-preview-card')
        self.assertContains(response, 'data-short-url-domain')
        self.assertContains(response, 'data-short-url-alias')
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

    def test_global_quick_create_form_does_not_include_note_field(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:settings'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="global-quick-note"')

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
        self.assertTrue(response.url.startswith(f"{reverse('common:domain_list')}?"))
        self.assertIn('tab=domains-create', response.url)
        self.assertIn('created_domain=', response.url)

    def test_domain_create_shows_action_notice_card(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_create'),
            {
                'name': 'brand-new.example.com',
                'active_tab': 'domains-create',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created_domain = Domain.objects.get(name='brand-new.example.com')
        self.assertContains(response, 'Domain added')
        self.assertContains(response, 'Open details')
        self.assertContains(response, reverse('common:domain_settings', kwargs={'pk': created_domain.pk}))
        self.assertContains(response, 'Keep adding')

    def test_domain_settings_page_shows_verify_and_delete_actions(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:domain_settings', kwargs={'pk': self.domain.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete domain')
        self.assertContains(response, 'Current password')
        self.assertContains(response, 'Service configuration')
        self.assertNotContains(response, 'Ownership verification pending')
        self.assertContains(response, 'data-tab-target="domain-overview"')
        self.assertContains(response, 'data-tab-target="domain-routing"')
        self.assertNotContains(response, 'data-tab-target="domain-root"')

    def test_domain_delete_requires_current_password(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_delete', kwargs={'pk': self.domain.pk}),
            {
                'next': reverse('common:domain_settings', kwargs={'pk': self.domain.pk}),
                'confirm_password': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Domain.objects.filter(pk=self.domain.pk).exists())
        self.assertContains(response, 'Enter your current password to delete this domain.')

    def test_domain_delete_rejects_wrong_password(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('common:domain_delete', kwargs={'pk': self.domain.pk}),
            {
                'next': reverse('common:domain_settings', kwargs={'pk': self.domain.pk}),
                'confirm_password': 'wrong-password',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Domain.objects.filter(pk=self.domain.pk).exists())
        self.assertContains(response, 'The password you entered is incorrect.')

    def test_pending_domain_settings_hide_service_configuration_until_verified(self):
        self.client.force_login(self.owner)
        self.domain.is_verified = False
        self.domain.host_allowed = False
        self.domain.dns_txt = 'shorty-test-token'
        self.domain.save(update_fields=['is_verified', 'host_allowed', 'dns_txt'])

        response = self.client.get(reverse('common:domain_settings', kwargs={'pk': self.domain.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ownership verification pending')
        self.assertNotContains(response, 'Service configuration')
        self.assertContains(response, 'DNS TXT token')

    @override_settings(CNAME_HOST_TARGET='edge.shorty.test')
    def test_domain_settings_cname_check_reports_success(self):
        self.client.force_login(self.owner)

        class FakeAnswer:
            def __init__(self, value):
                self.value = value

            def to_text(self):
                return self.value

        with patch('shorty.models.resolve_dns', return_value=[FakeAnswer('edge.shorty.test.')]):
            response = self.client.post(
                reverse('common:domain_check_cname', kwargs={'pk': self.domain.pk}),
                {
                    'next': reverse('common:domain_settings', kwargs={'pk': self.domain.pk}),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request['PATH_INFO'], reverse('common:domain_settings', kwargs={'pk': self.domain.pk}))
        self.assertContains(response, 'CNAME check passed.')
        self.assertContains(response, 'is ready to serve traffic')
        self.domain.refresh_from_db()
        self.assertTrue(self.domain.host_allowed)


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
        self.assertContains(response, 'Created')
        self.assertContains(response, 'Updated')
        self.assertContains(response, 'Last click')
        self.assertContains(response, 'QR code')
        self.assertContains(response, 'Link details')
        self.assertContains(response, 'Traffic sources')
        self.assertContains(response, 'Recent activity')
        self.assertNotContains(response, 'Share-ready code')
        self.assertNotContains(response, '<div class="section-label">Details</div>', html=False)

    def test_stats_view_shows_dash_for_missing_metadata(self):
        self.client.force_login(self.owner)
        self.surl.click_events.all().delete()
        Surl.objects.filter(pk=self.surl.pk).update(created_at=None, updated_at=None)

        response = self.client.get(reverse('common:url_stats', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<strong>Created</strong> -', html=True)
        self.assertContains(response, '<strong>Updated</strong> -', html=True)
        self.assertContains(response, '<strong>Last click</strong> -', html=True)

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

    def test_dashboard_hover_panel_shows_clicks_and_hides_empty_note(self):
        self.client.force_login(self.owner)
        self.surl.note = ''
        self.surl.visit_counts = 7
        self.surl.save(update_fields=['note', 'visit_counts'])

        response = self.client.get(reverse('common:url'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<strong>Clicks</strong>', html=False)
        self.assertContains(response, '<span class="hover-detail-value">7</span>', html=False)
        self.assertNotContains(response, '<strong>Note</strong>', html=False)

    def test_links_page_routes_to_detail_view(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:links'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-href="{reverse("common:url_stats", kwargs={"pk": self.surl.pk})}"')
        self.assertContains(response, reverse('common:url_stats', kwargs={'pk': self.surl.pk}))
        self.assertContains(response, 'data-tab-target="links-library"')
        self.assertContains(response, 'data-tab-target="links-create"')

    def test_edit_page_hides_tabs_and_shows_form_only(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url_edit', kwargs={'pk': self.surl.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit short link')
        self.assertNotContains(response, 'data-tab-target="links-library"')
        self.assertNotContains(response, 'data-tab-target="links-create"')
        self.assertNotContains(response, 'All short links')

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

    def test_dashboard_quick_create_form_does_not_include_note_field(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('common:url'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="quick-note"')

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

    @override_settings(DEBUG=True, RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET='')
    def test_login_page_shows_short_url_intro_panel(self):
        response = self.client.get(reverse('common:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Long URLs, made shorter and easier.')
        self.assertContains(response, 'Original URL')
        self.assertContains(response, 'Short URL')


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
