from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User


class UserForm(UserCreationForm):
    email = forms.EmailField(label='Email')
    privacy_consent = forms.BooleanField(
        label='I agree to the collection and use of personal information.',
        required=True,
        error_messages={
            'required': 'You must agree to the privacy notice to create an account.',
        },
    )

    class Meta:
        model = User
        fields = ("username", "password1", "password2", "email")


class AccountUpdateForm(forms.ModelForm):
    email = forms.EmailField(label='Email')

    class Meta:
        model = User
        fields = ("email",)


class EmailChangeRequestForm(forms.Form):
    new_email = forms.EmailField(label='New email')


class EmailChangeVerifyForm(forms.Form):
    verification_code = forms.CharField(label='Verification code', max_length=6)


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(label='Email')


class PasswordResetVerifyForm(SetPasswordForm):
    verification_code = forms.CharField(label='Verification code', max_length=6)


class UsernameReminderRequestForm(forms.Form):
    email = forms.EmailField(label='Email')
