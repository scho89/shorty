from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from common.views import get_url_wc_data
from shorty.models import Domain, Surl


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
        self.assertEqual(len(colors), 17)


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


class AccountSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='account-user',
            password='ComplexPass123!',
            email='before@example.com',
        )

    def test_account_settings_updates_email(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('common:account_settings'),
            {
                'action': 'email',
                'email': 'after@example.com',
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
