from django import forms
from shorty.models import Surl,Domain

class SurlForm(forms.ModelForm):
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
