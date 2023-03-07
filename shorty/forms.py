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
