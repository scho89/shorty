from django import forms
from django.utils import timezone
from shorty.models import Surl,Domain

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
        self.fields['expires_at'].input_formats = ['%Y-%m-%dT%H:%M']
        if not self.is_bound and not getattr(self.instance, 'pk', None):
            self.initial.setdefault('is_active', True)

        expires_at = self.initial.get('expires_at') or getattr(self.instance, 'expires_at', None)
        if expires_at:
            localized = timezone.localtime(expires_at) if timezone.is_aware(expires_at) else expires_at
            self.initial['expires_at'] = localized.strftime('%Y-%m-%dT%H:%M')

    class Meta:
        model = Surl
        fields = ['domain', 'alias','url','note', 'is_active', 'expires_at']
        widgets = {
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
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


class DomainForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ['name']

        labels = {
            'name':'Name'
        }
