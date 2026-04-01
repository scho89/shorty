from django import forms
from shorty.models import Surl,Domain

class SurlForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Domain.objects.filter(is_verified=True)
        if user is not None and user.is_authenticated:
            queryset = queryset.filter(owner=user)
        else:
            queryset = queryset.none()
        self.fields['domain'].queryset = queryset.order_by('name')
        self.fields['domain'].empty_label = 'Select domain'

    class Meta:
        model = Surl
        fields = ['domain', 'alias','url','note']

        labels = {
            'domain': 'Domain',
            'alias': 'Alias',
            'url': 'Origianl URL',
            'note': 'Note',
        }


class DomainForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ['name']

        labels = {
            'name':'Name'
        }
