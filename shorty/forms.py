from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from urllib.parse import urlparse

from shorty.models import Domain, FallbackDestination, GlobalRoutingSettings, Surl


def normalize_hostname(value):
    hostname = (value or '').strip().lower().rstrip('.')
    return hostname or ''


def is_shorty_managed_url(value):
    parsed = urlparse((value or '').strip())
    hostname = normalize_hostname(parsed.hostname)
    if not hostname:
        return False
    return Domain.objects.filter(name__iexact=hostname).exists()


class SurlForm(forms.ModelForm):
    def __init__(self, *args, user=None, allow_blank_alias=False, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Domain.objects.filter(is_verified=True)
        if user is not None and user.is_authenticated:
            queryset = queryset.filter(owner=user)
        else:
            queryset = queryset.none()
        self.fields['domain'].queryset = queryset.order_by('name')
        self.fields['domain'].empty_label = 'Select domain'
        self.fields['alias'].required = not allow_blank_alias
        self.fields['expires_at'].input_formats = ['%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M']
        if not self.is_bound and not getattr(self.instance, 'pk', None):
            self.initial.setdefault('is_active', True)

        expires_at = self.initial.get('expires_at') or getattr(self.instance, 'expires_at', None)
        if expires_at:
            localized = timezone.localtime(expires_at) if timezone.is_aware(expires_at) else expires_at
            self.initial['expires_at'] = localized.strftime('%Y-%m-%dT%H:%M')

    class Meta:
        model = Surl
        fields = ['domain', 'alias', 'url', 'note', 'is_active', 'expires_at']
        widgets = {
            'expires_at': forms.TextInput(attrs={'placeholder': 'YYYY-MM-DD 00:00', 'autocomplete': 'off'}),
        }
        labels = {
            'domain': 'Domain',
            'alias': 'Alias',
            'url': 'Origianl URL',
            'note': 'Note',
            'is_active': 'Link is active',
            'expires_at': 'Expires at',
        }

    def clean_expires_at(self):
        expires_at = self.cleaned_data.get('expires_at')
        if expires_at and expires_at <= timezone.now():
            raise forms.ValidationError('Expiration time must be in the future.')
        return expires_at

    def clean_url(self):
        url = (self.cleaned_data.get('url') or '').strip()
        if is_shorty_managed_url(url):
            raise forms.ValidationError('Destination URL cannot point to a Shorty-managed domain.')
        return url


class DomainForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ['name']
        labels = {
            'name': 'Name'
        }


class RoutingPolicyFormMixin:
    policy_specs = [
        ('root', 'Root', 'Welcome to our branded short link domain.'),
        ('missing_alias', 'Missing alias', 'This short link could not be found.'),
        ('inactive', 'Inactive', 'This short link is currently disabled.'),
        ('expired', 'Expired', 'This short link has expired.'),
    ]

    @staticmethod
    def label_from_fallback(destination):
        return f'{destination.name} -> {destination.url}'

    def setup_policy_fields(self, owner):
        fallback_destinations = FallbackDestination.objects.none()
        if owner is not None:
            fallback_destinations = FallbackDestination.objects.filter(owner=owner).order_by('name', 'pk')

        for policy_name, _label, placeholder in self.policy_specs:
            action_field = f'{policy_name}_action'
            fallback_field = f'{policy_name}_fallback'
            message_field = f'{policy_name}_message'
            self.fields[action_field].widget.attrs['class'] = 'select policy-action-select'
            self.fields[fallback_field].required = False
            self.fields[fallback_field].empty_label = 'Do not use a fallback URL'
            self.fields[fallback_field].queryset = fallback_destinations
            self.fields[fallback_field].label_from_instance = self.label_from_fallback
            self.fields[fallback_field].widget.attrs['class'] = 'select'
            self.fields[message_field].widget.attrs.update({'class': 'input', 'placeholder': placeholder})

    def clean_policy_fields(self, cleaned_data, *, allow_inherit):
        for policy_name, _label, _placeholder in self.policy_specs:
            action_field = f'{policy_name}_action'
            fallback_field = f'{policy_name}_fallback'
            message_field = f'{policy_name}_message'
            action = cleaned_data.get(action_field)
            fallback = cleaned_data.get(fallback_field)
            message = (cleaned_data.get(message_field) or '').strip()

            if allow_inherit and action == Domain.POLICY_ACTION_INHERIT:
                cleaned_data[fallback_field] = None
                cleaned_data[message_field] = ''
                continue

            if action == Domain.ROOT_ACTION_FALLBACK and not fallback:
                self.add_error(fallback_field, 'Select the fallback URL to use for this state.')
            if action in {Domain.MESSAGE_ACTION, Domain.ROOT_ACTION_SHOW_MESSAGE} and not message:
                self.add_error(message_field, 'Enter the message to show for this state.')

            if action != Domain.ROOT_ACTION_FALLBACK:
                cleaned_data[fallback_field] = None
            if action not in {Domain.MESSAGE_ACTION, Domain.ROOT_ACTION_SHOW_MESSAGE}:
                cleaned_data[message_field] = ''

            if fallback and getattr(self.instance, 'owner_id', None) and fallback.owner_id != self.instance.owner_id:
                self.add_error(fallback_field, 'Select a fallback URL from your workspace.')

        if self.errors:
            raise ValidationError('Review the routing policy fields and try again.')
        return cleaned_data


class DomainRoutingSettingsForm(RoutingPolicyFormMixin, forms.ModelForm):
    class Meta:
        model = Domain
        fields = [
            'root_action', 'root_fallback', 'root_message',
            'missing_alias_action', 'missing_alias_fallback', 'missing_alias_message',
            'inactive_action', 'inactive_fallback', 'inactive_message',
            'expired_action', 'expired_fallback', 'expired_message',
        ]
        labels = {
            'root_action': 'Root behavior',
            'root_fallback': 'Root fallback URL',
            'root_message': 'Root message',
            'missing_alias_action': 'Missing alias behavior',
            'missing_alias_fallback': 'Missing alias fallback URL',
            'missing_alias_message': 'Missing alias message',
            'inactive_action': 'Inactive behavior',
            'inactive_fallback': 'Inactive fallback URL',
            'inactive_message': 'Inactive message',
            'expired_action': 'Expired behavior',
            'expired_fallback': 'Expired fallback URL',
            'expired_message': 'Expired message',
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        owner = owner or getattr(self.instance, 'owner', None)
        self.setup_policy_fields(owner)

    def clean(self):
        cleaned_data = super().clean()
        return self.clean_policy_fields(cleaned_data, allow_inherit=True)


class GlobalRoutingSettingsForm(RoutingPolicyFormMixin, forms.ModelForm):
    class Meta:
        model = GlobalRoutingSettings
        fields = [
            'root_action', 'root_fallback', 'root_message',
            'missing_alias_action', 'missing_alias_fallback', 'missing_alias_message',
            'inactive_action', 'inactive_fallback', 'inactive_message',
            'expired_action', 'expired_fallback', 'expired_message',
        ]
        labels = {
            'root_action': 'Default root behavior',
            'root_fallback': 'Default root fallback URL',
            'root_message': 'Default root message',
            'missing_alias_action': 'Default missing alias behavior',
            'missing_alias_fallback': 'Default missing alias fallback URL',
            'missing_alias_message': 'Default missing alias message',
            'inactive_action': 'Default inactive behavior',
            'inactive_fallback': 'Default inactive fallback URL',
            'inactive_message': 'Default inactive message',
            'expired_action': 'Default expired behavior',
            'expired_fallback': 'Default expired fallback URL',
            'expired_message': 'Default expired message',
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        owner = owner or getattr(self.instance, 'owner', None)
        self.setup_policy_fields(owner)

    def clean(self):
        cleaned_data = super().clean()
        return self.clean_policy_fields(cleaned_data, allow_inherit=False)


class FallbackDestinationForm(forms.ModelForm):
    class Meta:
        model = FallbackDestination
        fields = ['name', 'url', 'note']
        labels = {
            'name': 'Name',
            'url': 'Destination URL',
            'note': 'Note',
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        for field_name in ['name', 'url', 'note']:
            self.fields[field_name].widget.attrs['class'] = 'input'
        self.fields['name'].widget.attrs['placeholder'] = 'Company homepage'
        self.fields['url'].widget.attrs['placeholder'] = 'https://company.example.com'
        self.fields['note'].widget.attrs['placeholder'] = 'Where this fallback should be used'

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        queryset = FallbackDestination.objects.none()
        if self.owner is not None:
            queryset = FallbackDestination.objects.filter(owner=self.owner)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.filter(name__iexact=name).exists():
            raise forms.ValidationError('This fallback URL name is already in use.')
        return name

    def clean_url(self):
        url = (self.cleaned_data.get('url') or '').strip()
        if is_shorty_managed_url(url):
            raise forms.ValidationError('Fallback URL cannot point to a Shorty-managed domain.')
        return url
