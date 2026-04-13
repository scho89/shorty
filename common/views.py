from datetime import timedelta
from django.conf import settings 
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import connection
from django.db.models import Count
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from django.views.decorators.http import require_POST
from common.forms import (
    EmailChangeRequestForm,
    EmailChangeVerifyForm,
    PasswordResetRequestForm,
    PasswordResetVerifyForm,
    UsernameReminderRequestForm,
    UserForm,
)
from shorty.forms import DomainForm, DomainRoutingSettingsForm, FallbackDestinationForm, GlobalRoutingSettingsForm, SurlForm
from shorty.models import ClickEvent, Domain, FallbackDestination, GlobalRoutingSettings, Surl

import json
import logging
import secrets
import sys
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import date
from urllib.error import URLError


logger=logging.getLogger('shorty')
SSL_LIST = getattr(settings, 'SSL_LIST', '')
ALIAS_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'
DOMAIN_BADGE_PALETTE = [
    ('#eff6ff', '#1d4ed8'),
    ('#ecfdf3', '#138a52'),
    ('#fff7ed', '#c27a12'),
    ('#fdf2f8', '#be185d'),
    ('#f5f3ff', '#6d28d9'),
    ('#eef2ff', '#4338ca'),
    ('#ecfeff', '#0f766e'),
    ('#fff1f2', '#be123c'),
]

User = get_user_model()
PASSWORD_RESET_CODE_PREFIX = 'password-reset-code'
EMAIL_CHANGE_CODE_PREFIX = 'email-change-code'
PASSWORD_RESET_SESSION_KEY = 'password_reset_email'


# Create your views here.
def style_form_fields(form):
    for field in form.fields.values():
        existing_classes = field.widget.attrs.get('class', '')
        field.widget.attrs['class'] = (f'{existing_classes} input').strip()
    return form


def normalize_email(value):
    return (value or '').strip().lower()


def build_verification_cache_key(prefix, identifier):
    return f'{prefix}:{identifier}'


def generate_verification_code():
    return f'{secrets.randbelow(1000000):06d}'


def store_verification_code(prefix, identifier, payload):
    cache.set(
        build_verification_cache_key(prefix, identifier),
        payload,
        timeout=settings.ACCOUNT_VERIFICATION_CODE_TTL,
    )


def get_verification_code(prefix, identifier):
    return cache.get(build_verification_cache_key(prefix, identifier))


def clear_verification_code(prefix, identifier):
    cache.delete(build_verification_cache_key(prefix, identifier))


def send_verification_email(recipient, subject, intro, code):
    send_mail(
        subject=subject,
        message=f'{intro}\n\nVerification code: {code}\n\nThis code expires in {settings.ACCOUNT_VERIFICATION_CODE_TTL // 60} minutes.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_username_reminder_email(recipient, usernames):
    username_lines = '\n'.join(f'- {username}' for username in usernames)
    send_mail(
        subject='Shorty username reminder',
        message=(
            'The following Shorty username(s) are registered with this email address:\n\n'
            f'{username_lines}\n\n'
            'If you did not request this email, you can ignore it.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def dispatch_verification_email(recipient, subject, intro, code):
    try:
        send_verification_email(recipient, subject, intro, code)
        return True
    except Exception:
        logger.exception('Failed to send verification email to %s', recipient)
        return False


def dispatch_username_reminder_email(recipient, usernames):
    try:
        send_username_reminder_email(recipient, usernames)
        return True
    except Exception:
        logger.exception('Failed to send username reminder email to %s', recipient)
        return False


def get_password_reset_user(email):
    return User.objects.filter(email__iexact=email).order_by('pk').first()


def get_users_by_email(email):
    return list(User.objects.filter(email__iexact=email).order_by('username'))


def get_pending_email_change(user):
    return get_verification_code(EMAIL_CHANGE_CODE_PREFIX, user.pk)


def build_password_reset_forms(request):
    request_form = style_form_fields(PasswordResetRequestForm())
    verify_form = None
    pending_email = request.session.get(PASSWORD_RESET_SESSION_KEY)
    pending_reset = None

    if pending_email:
        pending_reset = get_verification_code(PASSWORD_RESET_CODE_PREFIX, normalize_email(pending_email))
        if pending_reset:
            verify_form = style_form_fields(
                PasswordResetVerifyForm(
                    user=User.objects.get(pk=pending_reset['user_id']),
                )
            )
        else:
            request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
            pending_email = None

    return request_form, verify_form, pending_email


def recaptcha_is_bypassed():
    return settings.DEBUG or 'test' in sys.argv


def get_recaptcha_context():
    return {
        'recaptcha_enabled': bool(settings.RECAPTCHA_SITE_KEY) and not recaptcha_is_bypassed(),
        'recaptcha_site_key': settings.RECAPTCHA_SITE_KEY,
        'recaptcha_bypassed': recaptcha_is_bypassed(),
    }


def get_recaptcha_error_message(result):
    error_codes = result.get('error-codes', [])
    if 'recaptcha-not-configured' in error_codes:
        return 'reCAPTCHA is not configured. Check the server environment settings.'
    if 'recaptcha-unavailable' in error_codes:
        return 'The reCAPTCHA verification service is unavailable right now. Please try again shortly.'
    return 'Please complete the reCAPTCHA check and try again.'

def get_cname_host_target():
    return (getattr(settings, 'CNAME_HOST_TARGET', '') or '').strip()


def signin(request):
    
    if request.user.is_authenticated:
        return redirect('common:url')
    
    if request.method == "POST":
        
        result = recaptcha_result(request)
        
        if result['success']:
        
            username = request.POST['username']
            password = request.POST['password']
            
            user = authenticate(request,username=username,password=password)
            
            if user is not None:
                messages.success(request, 'Signed in successfully.')
                login(request, user)
                return redirect('common:url')
            
            else:
                messages.error(request, 'The username or password is incorrect.')
                
        else:
            messages.error(request, get_recaptcha_error_message(result))
    
    return render(request, 'common/login.html', get_recaptcha_context())
def signup(request):
    if request.method == "POST":
        form = UserForm(request.POST)

        # ''' Begin reCAPTCHA validation '''
        result = recaptcha_result(request)
        # ''' End reCAPTCHA validation '''

        if result['success']:
            if form.is_valid():
                form.save()
                username = form.cleaned_data.get('username')
                raw_password = form.cleaned_data.get('password1')
                user = authenticate(username=username, password=raw_password)
                login(request, user)
                messages.success(request, 'Account created successfully.')
                return redirect('common:url')
            
        else:
            messages.error(request, get_recaptcha_error_message(result))

        
        # if form.is_valid():
        #     form.save()
        #     username = form.cleaned_data.get('username')
        #     raw_password = form.cleaned_data.get('password1')
        #     user = authenticate(username=username, password=raw_password)
        #     login(request, user)
        #     return redirect('common:url')

    else:
        form = UserForm()
        
    return render(request, 'common/signup.html', {'form': form, **get_recaptcha_context()})


def username_reminder_request(request):
    form = style_form_fields(UsernameReminderRequestForm())

    if request.method == 'POST':
        form = style_form_fields(UsernameReminderRequestForm(request.POST))
        if form.is_valid():
            email = form.cleaned_data['email']
            users = get_users_by_email(email)
            if users:
                usernames = [user.username for user in users]
                if not dispatch_username_reminder_email(email, usernames):
                    form.add_error(None, 'We could not send the reminder email. Check your email settings and try again.')
                    return render(request, 'common/username_reminder_request.html', {'form': form})
            messages.success(request, 'If an account matches that email, the username reminder has been sent.')
            return redirect('common:login')

    return render(request, 'common/username_reminder_request.html', {'form': form})


def page_not_found(request, exception):
    return render(request, 'common/404.html', {}, status=404)

def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        db_status = 'ok'
        status_code = 200
    except Exception as exc:
        db_status = f'error: {exc}'
        status_code = 503

    return JsonResponse({'status': 'ok' if status_code == 200 else 'degraded', 'db': db_status}, status=status_code)


def caddy_ask(request):
    domain = (request.GET.get('domain') or '').strip().lower().rstrip('.')
    if not domain:
        return JsonResponse({'status': 'denied', 'reason': 'missing domain'}, status=400)

    allowed = Domain.objects.filter(name__iexact=domain, host_allowed=True).exists()
    if not allowed:
        return JsonResponse({'status': 'denied', 'domain': domain}, status=403)

    return JsonResponse({'status': 'ok', 'domain': domain}, status=200)


def generate_random_alias(length=7):
    return ''.join(secrets.choice(ALIAS_ALPHABET) for _ in range(length))


def assign_unique_alias(surl, max_attempts=10):
    for _ in range(max_attempts):
        candidate = generate_random_alias()
        if not Surl.objects.filter(domain=surl.domain, alias=candidate).exists():
            surl.alias = candidate
            surl.short_url = f'{surl.domain.name}/{candidate}'
            return True
    return False


def help_page(request):
    cname_target = get_cname_host_target()
    context = {
        'cname_target': cname_target,
        'cname_target_configured': bool(cname_target),
    }
    return render(request, 'common/help.html', context)


@login_required(login_url='common:login')
def account_settings(request):
    email_request_form = style_form_fields(
        EmailChangeRequestForm(initial={'new_email': request.user.email})
    )
    email_verify_form = style_form_fields(EmailChangeVerifyForm(prefix='email_verify'))
    password_form = style_form_fields(PasswordChangeForm(user=request.user, prefix='password'))
    pending_email_change = get_pending_email_change(request.user)

    if request.method == "POST":
        action = request.POST.get('action')

        if action == 'email_request':
            email_request_form = style_form_fields(EmailChangeRequestForm(request.POST))
            if email_request_form.is_valid():
                new_email = email_request_form.cleaned_data['new_email']
                if normalize_email(new_email) == normalize_email(request.user.email):
                    email_request_form.add_error('new_email', 'Enter a different email address.')
                elif User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
                    email_request_form.add_error('new_email', 'This email address is already in use.')
                else:
                    code = generate_verification_code()
                    if dispatch_verification_email(
                        new_email,
                        'Shorty email change verification code',
                        'Use this code to confirm your new Shorty email address.',
                        code,
                    ):
                        store_verification_code(
                            EMAIL_CHANGE_CODE_PREFIX,
                            request.user.pk,
                            {'email': new_email, 'code': code},
                        )
                        messages.success(request, 'A verification code was sent to your new email address.')
                        return redirect('common:account_settings')
                    email_request_form.add_error(None, 'We could not send the verification email. Check your email settings and try again.')
            email_verify_form = style_form_fields(EmailChangeVerifyForm(prefix='email_verify'))
            password_form = style_form_fields(PasswordChangeForm(user=request.user, prefix='password'))

        elif action == 'email_verify':
            email_verify_form = style_form_fields(EmailChangeVerifyForm(request.POST, prefix='email_verify'))
            pending_email_change = get_pending_email_change(request.user)
            if not pending_email_change:
                messages.error(request, 'Your email verification code expired. Request a new code.')
            elif email_verify_form.is_valid():
                submitted_code = email_verify_form.cleaned_data['verification_code']
                if submitted_code != pending_email_change['code']:
                    email_verify_form.add_error('verification_code', 'Enter the correct verification code.')
                else:
                    request.user.email = pending_email_change['email']
                    request.user.save(update_fields=['email'])
                    clear_verification_code(EMAIL_CHANGE_CODE_PREFIX, request.user.pk)
                    messages.success(request, 'Email updated.')
                    return redirect('common:account_settings')
            email_request_form = style_form_fields(
                EmailChangeRequestForm(initial={'new_email': pending_email_change['email'] if pending_email_change else request.user.email})
            )
            password_form = style_form_fields(PasswordChangeForm(user=request.user, prefix='password'))

        elif action == 'password':
            email_request_form = style_form_fields(
                EmailChangeRequestForm(initial={'new_email': request.user.email})
            )
            email_verify_form = style_form_fields(EmailChangeVerifyForm(prefix='email_verify'))
            password_form = style_form_fields(
                PasswordChangeForm(user=request.user, data=request.POST, prefix='password')
            )
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password updated.')
                return redirect('common:account_settings')

        pending_email_change = get_pending_email_change(request.user)

    context = {
        'email_request_form': email_request_form,
        'email_verify_form': email_verify_form,
        'password_form': password_form,
        'pending_email_change': pending_email_change,
    }
    return render(request, 'common/account_settings.html', context)


def password_reset_request(request):
    request_form, _, pending_email = build_password_reset_forms(request)

    if request.method == 'POST':
        request_form = style_form_fields(PasswordResetRequestForm(request.POST))
        if request_form.is_valid():
            email = request_form.cleaned_data['email']
            user = get_password_reset_user(email)
            if user and user.has_usable_password():
                code = generate_verification_code()
                normalized_email = normalize_email(email)
                if dispatch_verification_email(
                    email,
                    'Shorty password reset verification code',
                    'Use this code to reset your Shorty password.',
                    code,
                ):
                    store_verification_code(
                        PASSWORD_RESET_CODE_PREFIX,
                        normalized_email,
                        {'user_id': user.pk, 'code': code},
                    )
                    request.session[PASSWORD_RESET_SESSION_KEY] = normalized_email
                else:
                    request_form.add_error(None, 'We could not send the reset email. Check your email settings and try again.')
                    return render(request, 'common/password_reset_request.html', {'request_form': request_form, 'pending_reset_email': pending_email})
            else:
                request.session[PASSWORD_RESET_SESSION_KEY] = normalize_email(email)
            messages.success(request, 'If an account matches that email, a verification code has been sent.')
            return redirect('common:password_reset_verify')

    context = {
        'request_form': request_form,
        'pending_reset_email': pending_email,
    }
    return render(request, 'common/password_reset_request.html', context)


def password_reset_verify(request):
    request_form, verify_form, pending_email = build_password_reset_forms(request)

    if not pending_email:
        messages.info(request, 'Start by requesting a password reset code.')
        return redirect('common:password_reset_request')

    pending_reset = get_verification_code(PASSWORD_RESET_CODE_PREFIX, normalize_email(pending_email))
    if not pending_reset:
        messages.error(request, 'Your password reset code expired. Request a new code.')
        return redirect('common:password_reset_request')

    reset_user = User.objects.get(pk=pending_reset['user_id'])

    if request.method == 'POST':
        verify_form = style_form_fields(PasswordResetVerifyForm(user=reset_user, data=request.POST))
        if verify_form.is_valid():
            submitted_code = verify_form.cleaned_data['verification_code']
            if submitted_code != pending_reset['code']:
                verify_form.add_error('verification_code', 'Enter the correct verification code.')
            else:
                verify_form.save()
                clear_verification_code(PASSWORD_RESET_CODE_PREFIX, normalize_email(pending_email))
                request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
                messages.success(request, 'Your password has been reset. Sign in with your new password.')
                return redirect('common:login')

    context = {
        'request_form': request_form,
        'verify_form': verify_form,
        'pending_reset_email': pending_email,
    }
    return render(request, 'common/password_reset_verify.html', context)

@login_required(login_url='common:login')
def domain_list(request):
    
    # if request.method == "GET":
    if request.user.is_authenticated:
        domains = (
            Domain.objects.filter(owner__username=request.user.username)
            .annotate(link_count=Count('surl'))
            .order_by('name')
        )
        context = {'domains':domains, 'form': DomainForm()}
        return render(request,'common/domain.html',context=context)    

    else:
        return render(request,'shorty/index.html')    

def get_owned_domain(request, pk):
    return get_object_or_404(
        Domain.objects.select_related('owner'),
        pk=pk,
        owner=request.user,
    )


def get_global_routing_settings(owner):
    settings_obj, _created = GlobalRoutingSettings.objects.get_or_create(owner=owner)
    return settings_obj


def build_policy_sections(form, scope_label, include_inherit):
    sections = []
    labels = {
        'root': 'Root',
        'missing_alias': 'Missing alias',
        'inactive': 'Inactive',
        'expired': 'Expired',
    }
    descriptions = {
        'root': f'Choose what happens when someone opens the {scope_label} root URL.',
        'missing_alias': f'Choose what happens when an alias does not exist on the {scope_label}.',
        'inactive': f'Choose what happens when a matching alias exists but is inactive on the {scope_label}.',
        'expired': f'Choose what happens when a matching alias exists but is expired on the {scope_label}.',
    }
    for key in ['root', 'missing_alias', 'inactive', 'expired']:
        sections.append({
            'key': key,
            'title': labels[key],
            'description': descriptions[key],
            'action_field': form[f'{key}_action'],
            'fallback_field': form[f'{key}_fallback'],
            'message_field': form[f'{key}_message'],
            'include_inherit': include_inherit,
        })
    return sections


def build_settings_context(request, fallback_form=None, global_form=None):
    fallback_destinations = list(
        FallbackDestination.objects.filter(owner=request.user).order_by('name', 'pk')
    )
    fallback_in_use = (
        Domain.objects.filter(owner=request.user)
        .exclude(root_fallback=None, missing_alias_fallback=None, inactive_fallback=None, expired_fallback=None)
        .count()
    )
    global_settings = get_global_routing_settings(request.user)
    global_form = global_form or GlobalRoutingSettingsForm(instance=global_settings, owner=request.user)
    return {
        'fallback_destinations': fallback_destinations,
        'fallback_form': fallback_form or FallbackDestinationForm(owner=request.user),
        'global_settings_form': global_form,
        'global_policy_sections': build_policy_sections(global_form, 'workspace', include_inherit=False),
        'fallback_count': len(fallback_destinations),
        'fallback_in_use': fallback_in_use,
    }


def redirect_with_tab(route_name, *, tab=None, kwargs=None):
    url = reverse(route_name, kwargs=kwargs)
    if tab:
        return redirect(f'{url}?{urlencode({"tab": tab})}')
    return redirect(url)


def append_tab_to_path(path, tab):
    if not path or not tab or not str(path).startswith('/'):
        return path

    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['tab'] = tab
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def append_query_params_to_path(path, **params):
    if not path or not str(path).startswith('/'):
        return path

    clean_params = {key: value for key, value in params.items() if value not in (None, '')}
    if not clean_params:
        return path

    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(clean_params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def stash_global_quick_create_state(request, redirect_target):
    post_data = request.POST.copy()
    post_data.pop('csrfmiddlewaretoken', None)
    request.session['global_quick_create_state'] = {
        'next': redirect_target,
        'data': post_data.dict(),
    }


@login_required(login_url='common:login')
def settings_page(request):
    context = build_settings_context(request)
    return render(request, 'common/settings.html', context)


@login_required(login_url='common:login')
@require_POST
def fallback_destination_create(request):
    form = FallbackDestinationForm(request.POST, owner=request.user)
    active_tab = (request.POST.get('active_tab') or '').strip()
    if form.is_valid():
        destination = form.save(commit=False)
        destination.owner = request.user
        destination.save()
        messages.success(request, f'Fallback URL {destination.name} was added.')
        return redirect_with_tab('common:settings', tab=active_tab)

    context = build_settings_context(request, fallback_form=form)
    return render(request, 'common/settings.html', context)


@login_required(login_url='common:login')
@require_POST
def global_routing_settings_update(request):
    settings_obj = get_global_routing_settings(request.user)
    form = GlobalRoutingSettingsForm(request.POST, instance=settings_obj, owner=request.user)
    active_tab = (request.POST.get('active_tab') or '').strip()
    if form.is_valid():
        form.save()
        messages.success(request, 'Global routing defaults were updated.')
        return redirect_with_tab('common:settings', tab=active_tab)

    context = build_settings_context(request, global_form=form)
    return render(request, 'common/settings.html', context)


@login_required(login_url='common:login')
@require_POST
def fallback_destination_delete(request, pk):
    destination = get_object_or_404(FallbackDestination, pk=pk, owner=request.user)
    active_tab = (request.POST.get('active_tab') or '').strip()
    destination_name = destination.name
    destination.delete()
    messages.success(request, f'Fallback URL {destination_name} was deleted.')
    return redirect_with_tab('common:settings', tab=active_tab)


@login_required(login_url='common:login')
def domain_settings(request, pk):
    domain = get_owned_domain(request, pk)
    form = DomainRoutingSettingsForm(instance=domain, owner=request.user)
    context = build_domain_settings_context(request, domain, form)
    return render(request, 'common/domain_settings.html', context)


def build_domain_settings_context(request, domain, form):
    fallback_options = FallbackDestination.objects.filter(owner=request.user).order_by('name', 'pk')
    cname_target = get_cname_host_target()
    return {
        'domain': domain,
        'form': form,
        'fallback_options': fallback_options,
        'link_count': Surl.objects.filter(domain=domain).count(),
        'policy_sections': build_policy_sections(form, domain.name, include_inherit=True),
        'cname_target': cname_target,
        'cname_target_configured': bool(cname_target),
        'domain_ready': bool(domain.is_verified and domain.host_allowed),
    }


@login_required(login_url='common:login')
@require_POST
def domain_settings_update(request, pk):
    domain = get_owned_domain(request, pk)
    form = DomainRoutingSettingsForm(request.POST, instance=domain, owner=request.user)
    active_tab = (request.POST.get('active_tab') or '').strip()
    if form.is_valid():
        form.save()
        messages.success(request, f'Domain settings for {domain.name} were updated.')
        return redirect_with_tab('common:domain_settings', kwargs={'pk': domain.pk}, tab=active_tab)

    context = build_domain_settings_context(request, domain, form)
    return render(request, 'common/domain_settings.html', context)


@login_required(login_url='common:login')
@require_POST
def domain_check_cname(request, pk):
    domain = get_owned_domain(request, pk)
    status = domain.get_cname_status()
    redirect_target = append_tab_to_path(
        request.POST.get('next') or reverse('common:domain_settings', kwargs={'pk': domain.pk}),
        'domain-overview',
    )

    if not status['configured']:
        if domain.host_allowed:
            domain.host_allowed = False
            domain.save(update_fields=['host_allowed'])
        messages.error(request, 'CNAME target is not configured on this server. Set CNAME_HOST_TARGET first.')
        return redirect(redirect_target)

    if status['matches']:
        if not domain.host_allowed:
            domain.host_allowed = True
            domain.save(update_fields=['host_allowed'])
        if domain.is_verified:
            messages.success(request, f'CNAME check passed. {domain.name} points to {status["expected_target"]} and is ready to serve traffic.')
        else:
            messages.success(request, f'CNAME check passed. {domain.name} points to {status["expected_target"]}. Verify ownership to finish setup.')
        return redirect(redirect_target)

    if domain.host_allowed:
        domain.host_allowed = False
        domain.save(update_fields=['host_allowed'])
    if status['resolved_targets']:
        resolved_targets = ', '.join(status['resolved_targets'])
        messages.error(
            request,
            f'CNAME check failed. Expected {status["expected_target"]}, but found {resolved_targets}.',
        )
        return redirect(redirect_target)

    messages.error(
        request,
        f'CNAME check failed. No CNAME answer was found for {domain.name}. Expected {status["expected_target"]}.',
    )
    return redirect(redirect_target)


@login_required(login_url='common:login')    
def url(request):
    if request.method == "GET":
        if request.user.is_authenticated:
            domains, surls = get_owned_objects(request)
            dashboard_form = SurlForm(user=request.user, allow_blank_alias=True)
            link_form = SurlForm(user=request.user, allow_blank_alias=True)
            created_link_notice = None
            created_pk = (request.GET.get('created') or '').strip()
            if created_pk.isdigit():
                created_surl = Surl.objects.filter(pk=int(created_pk), domain__owner=request.user).only('pk', 'short_url').first()
                if created_surl:
                    created_link_notice = {
                        'pk': created_surl.pk,
                        'short_url': created_surl.short_url,
                    }
            context = build_url_context(
                domains=domains,
                surls=surls,
                dashboard_form=dashboard_form,
                link_form=link_form,
                created_link_notice=created_link_notice,
                created_link_keep_adding_href='#quick-create',
            )
            return render(request,'common/dashboard.html',context=context)    

        else:
            return render(request,'common/dashboard.html')    


@login_required(login_url='common:login')
def links(request):
    if request.method == "GET":
        domains, surls = get_owned_objects(request)
        selected_domain_id = (request.GET.get('domain') or '').strip()
        search_query = (request.GET.get('q') or '').strip()
        created_link_notice = None
        created_pk = (request.GET.get('created') or '').strip()
        if selected_domain_id:
            surls = surls.filter(domain_id=selected_domain_id)
        if search_query:
            surls = surls.filter(
                Q(alias__icontains=search_query)
                | Q(url__icontains=search_query)
                | Q(note__icontains=search_query)
                | Q(short_url__icontains=search_query)
                | Q(domain__name__icontains=search_query)
            )
        surls = surls.order_by('-visit_counts')
        if created_pk.isdigit():
            created_surl = Surl.objects.filter(pk=int(created_pk), domain__owner=request.user).only('pk', 'short_url').first()
            if created_surl:
                created_link_notice = {
                    'pk': created_surl.pk,
                    'short_url': created_surl.short_url,
                }
        dashboard_form = SurlForm(user=request.user, allow_blank_alias=True)
        link_form = SurlForm(user=request.user, allow_blank_alias=True)
        context = build_url_context(
            domains=domains,
            surls=surls,
            dashboard_form=dashboard_form,
            link_form=link_form,
            selected_domain_id=selected_domain_id,
            search_query=search_query,
            created_link_notice=created_link_notice,
            created_link_keep_adding_href='#links-create',
        )
        return render(request, 'common/links.html', context=context)

    return redirect('common:links')

@login_required(login_url='common:login')
@require_POST
def url_create(request):
    if request.user.is_authenticated:
        mode = (request.POST.get('mode') or '').strip()
        is_quick_create = mode == 'quick'
        is_global_quick_create = mode == 'global_quick'
        form = SurlForm(request.POST, user=request.user, allow_blank_alias=True)
        redirect_target = request.POST.get('next') or 'common:links'
        active_tab = (request.POST.get('active_tab') or '').strip()
        template_name = 'common/dashboard.html' if str(redirect_target).startswith('/_common_/url') else 'common/links.html'
        if form.is_valid():
            surl = form.save(commit=False)
            surl.domain = form.cleaned_data['domain']
            if is_quick_create or is_global_quick_create:
                surl.is_active = True
            surl.alias = (surl.alias or '').strip()
            surl.short_url = str(surl.domain.name) + "/" + surl.alias
            if not surl.alias and not assign_unique_alias(surl):
                form.add_error('alias', 'Could not generate a unique alias. Please try again.')
                if is_global_quick_create and redirect_target.startswith('/'):
                    stash_global_quick_create_state(request, redirect_target)
                    return redirect(redirect_target)
                domains, surls = get_owned_objects(request)
                context = build_url_context(
                    domains=domains,
                    surls=surls,
                    dashboard_form=form if is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
                    link_form=form if not is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
                )
                return render(request, template_name, context=context)
            try:
                surl.validate_unique()
                surl.save()
                if is_quick_create:
                    dashboard_url = reverse('common:url')
                    return redirect(f'{dashboard_url}?created={surl.pk}')
            except ValidationError as e:
                if is_global_quick_create and redirect_target.startswith('/'):
                    stash_global_quick_create_state(request, redirect_target)
                    return redirect(redirect_target)
                domains, surls = get_owned_objects(request)
                context = build_url_context(
                    domains=domains,
                    surls=surls,
                    dashboard_form=form if is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
                    link_form=form if not is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
                    e=e,
                )
                return render(request, template_name, context=context)
        else:
            if is_global_quick_create and redirect_target.startswith('/'):
                stash_global_quick_create_state(request, redirect_target)
                return redirect(redirect_target)
            domains, surls = get_owned_objects(request)
            context = build_url_context(
                domains=domains,
                surls=surls,
                dashboard_form=form if is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
                link_form=form if not is_quick_create else SurlForm(user=request.user, allow_blank_alias=True),
            )
            return render(request, template_name, context=context)

        if redirect_target.startswith('/'):
            redirect_path = append_tab_to_path(redirect_target, active_tab)
            if not is_quick_create:
                redirect_path = append_query_params_to_path(redirect_path, created=surl.pk)
            return redirect(redirect_path)
        return redirect(redirect_target)

    return HttpResponse('url created.')

def get_owned_objects(request):
    domains = Domain.objects.filter(owner=request.user).order_by('name')
    surls = Surl.objects.filter(domain__in=domains)
    surls = surls.order_by('-visit_counts')
    return domains, surls


def get_owned_surl(request, pk):
    return get_object_or_404(
        Surl.objects.select_related('domain'),
        pk=pk,
        domain__owner=request.user,
    )


def build_url_context(domains, surls, dashboard_form=None, link_form=None, selected_domain_id='', search_query='', **extra):
    domains = list(domains)
    surls = list(surls)
    domain_badge_styles = get_domain_badge_styles(domains)

    for surl in surls:
        surl.domain_badge_style = domain_badge_styles.get(
            surl.domain.name,
            'background:#eff6ff;color:#1d4ed8;'
        )
        surl.status_label, surl.status_tone = get_surl_status_display(surl)

    insights = get_url_insights(surls)

    context = {
        'surls': surls,
        'domains': domains,
        'dashboard_form': dashboard_form,
        'link_form': link_form,
        'wc_data': insights['traffic_items'],
        'top_links': insights['top_links'],
        'rising_links': insights['rising_links'],
        'domain_trends': insights['domain_trends'],
        'selected_domain_id': str(selected_domain_id or ''),
        'search_query': search_query,
    }
    context.update(extra)
    return context


def get_surl_status_display(surl):
    if surl.is_expired:
        return 'Expired', 'warning'
    if not surl.is_active:
        return 'Disabled', 'warning'
    return 'Active', 'success'


def get_domain_badge_styles(domains):
    styles = {}
    for index, domain in enumerate(domains):
        background, color = DOMAIN_BADGE_PALETTE[index % len(DOMAIN_BADGE_PALETTE)]
        styles[domain.name] = f'background:{background};color:{color};'
    return styles


def get_url_insights(surls):
    surls = list(surls)
    top_links = build_top_links(surls)
    domain_trends = build_domain_trends(surls)
    rising_links = build_rising_links(surls)
    traffic_items = build_traffic_items(top_links, rising_links, domain_trends)

    return {
        'top_links': top_links,
        'rising_links': rising_links,
        'domain_trends': domain_trends,
        'traffic_items': traffic_items,
    }


def build_insight_link_payload(surl, **extra):
    note = (surl.note or '').strip()
    payload = {
        'pk': surl.pk,
        'alias': surl.alias,
        'short_url': surl.short_url,
        'url': surl.url,
        'note': note,
        'has_note': bool(note),
        'visit_counts': surl.visit_counts,
        'domain_name': surl.domain.name,
    }
    payload.update(extra)
    return payload


def build_top_links(surls):
    ranked = sorted(surls, key=lambda surl: (-surl.visit_counts, surl.alias.lower()))
    return [
        build_insight_link_payload(surl, rank=index)
        for index, surl in enumerate(ranked[:3], start=1)
    ]


def build_rising_links(surls):
    surl_map = {surl.id: surl for surl in surls}
    if not surl_map:
        return []

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    recent_counts = dict(
        ClickEvent.objects.filter(surl_id__in=surl_map, created_at__gte=seven_days_ago)
        .values('surl_id')
        .annotate(total=Count('id'))
        .values_list('surl_id', 'total')
    )
    previous_counts = dict(
        ClickEvent.objects.filter(
            surl_id__in=surl_map,
            created_at__gte=fourteen_days_ago,
            created_at__lt=seven_days_ago,
        )
        .values('surl_id')
        .annotate(total=Count('id'))
        .values_list('surl_id', 'total')
    )

    rising = []
    for surl_id, surl in surl_map.items():
        recent_total = recent_counts.get(surl_id, 0)
        previous_total = previous_counts.get(surl_id, 0)
        delta = recent_total - previous_total
        if recent_total <= 0 or delta <= 0:
            continue

        rising.append(build_insight_link_payload(
            surl,
            recent_total=recent_total,
            previous_total=previous_total,
            delta=delta,
        ))

    rising.sort(key=lambda item: (-item['delta'], -item['recent_total'], item['alias'].lower()))
    return rising[:5]


def build_domain_trends(surls):
    grouped = {}
    for surl in surls:
        bucket = grouped.setdefault(
            surl.domain.name,
            {'domain_name': surl.domain.name, 'links': 0, 'visits': 0},
        )
        bucket['links'] += 1
        bucket['visits'] += surl.visit_counts

    items = sorted(grouped.values(), key=lambda item: (-item['visits'], item['domain_name']))
    max_visits = max((item['visits'] for item in items), default=0)
    scale_base = max(max_visits, 1)

    for item in items:
        item['share'] = max(12, round(item['visits'] / scale_base * 100)) if items else 12

    return items


def build_traffic_items(top_links, rising_links, domain_trends):
    items = []

    for item in top_links:
        items.append({
            'label': f"#{item['rank']}",
            'title': item['alias'],
            'subtitle': item['domain_name'],
            'metric': f"{item['visit_counts']} visits",
            'url': item['url'],
        })

    for item in rising_links[:3]:
        items.append({
            'label': 'Up',
            'title': item['alias'],
            'subtitle': 'Last 7 days',
            'metric': f"+{item['delta']} clicks",
            'url': item['url'],
        })

    for item in domain_trends[:3]:
        items.append({
            'label': 'Domain',
            'title': item['domain_name'],
            'subtitle': f"{item['links']} links",
            'metric': f"{item['visits']} visits",
            'url': None,
        })

    return items[:12]


def build_stats_timeline(surl, days=14):
    today = timezone.localdate()
    start_day = today - timedelta(days=days - 1)
    counts = OrderedDict(
        (start_day + timedelta(days=index), 0)
        for index in range(days)
    )
    daily_counts = (
        ClickEvent.objects.filter(surl=surl, created_at__date__gte=start_day)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'))
        .order_by('day')
    )
    for item in daily_counts:
        day = item['day']
        if isinstance(day, date) and day in counts:
            counts[day] = item['total']

    peak = max(counts.values(), default=0)
    timeline = []
    total_days = max(len(counts), 1)
    chart_height = 100
    baseline = 92

    for index, (day, total) in enumerate(counts.items()):
        ratio = total / max(peak, 1)
        y = baseline - round(ratio * 72)
        timeline.append({
            'label': day.strftime('%m-%d'),
            'total': total,
            'height': max(12, round(ratio * 100)),
            'x': round(((index + 0.5) / total_days) * 100, 2),
            'y': y,
        })

    timeline_points = ' '.join(f"{item['x']},{item['y']}" for item in timeline)
    for item in timeline:
        item['tooltip_y'] = max(item['y'] - 10, 8)

    return {
        'items': timeline,
        'points': timeline_points,
        'peak': peak,
        'chart_height': chart_height,
    }


def build_top_breakdown(surl, field_name, empty_label):
    rows = (
        ClickEvent.objects.filter(surl=surl)
        .values(field_name)
        .annotate(total=Count('id'))
        .order_by('-total', field_name)[:5]
    )
    items = []
    for row in rows:
        raw_value = (row.get(field_name) or '').strip()
        items.append({
            'label': raw_value or empty_label,
            'total': row['total'],
        })
    return items


@login_required(login_url='common:login')
def url_stats(request, pk):
    surl = get_owned_surl(request, pk)
    timeline = build_stats_timeline(surl)
    referrers = build_top_breakdown(surl, 'referrer', 'Direct / Unknown')
    browsers = build_top_breakdown(surl, 'browser', 'Unknown')
    recent_events = list(
        surl.click_events.order_by('-created_at').values('created_at', 'referrer', 'browser')[:10]
    )

    context = {
        'surl': surl,
        'timeline': timeline,
        'referrers': referrers,
        'browsers': browsers,
        'recent_events': recent_events,
    }
    return render(request, 'common/url_stats.html', context)


@login_required(login_url='common:login')
def url_qr_code(request, pk):
    surl = get_owned_surl(request, pk)

    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        logger.exception('qrcode dependency is not installed')
        return HttpResponse('QR code support is unavailable.', status=500)

    qr = qrcode.make(
        f'https://{surl.short_url}',
        image_factory=SvgPathImage,
        box_size=8,
        border=2,
    )
    response = HttpResponse(content_type='image/svg+xml')
    response['Content-Disposition'] = f'inline; filename="shorty-{surl.alias}-qr.svg"'
    qr.save(response)
    return response


@login_required(login_url='common:login')
@require_POST
def url_toggle_active(request, pk):
    surl = get_owned_surl(request, pk)
    surl.is_active = not surl.is_active
    surl.save(update_fields=['is_active'])

    state_label = 'enabled' if surl.is_active else 'disabled'
    messages.success(request, f'URL {surl.short_url} was {state_label}.')

    redirect_target = request.POST.get('next')
    if redirect_target and redirect_target.startswith('/'):
        return redirect(redirect_target)
    return redirect('common:url_stats', pk=surl.pk)

@login_required(login_url='common:login')
@require_POST
def url_delete(request,pk):
    if request.user.is_authenticated:
        surl = get_owned_surl(request, pk)
        if surl.domain.owner.username == request.user.username:
            surl.delete()
            messages.success(request, f'URL {surl.short_url} was deleted.')
        else:
            messages.error(request, 'Only links you own can be deleted.')
            return render(request,'common/links.html')

    return redirect('common:links')

@login_required(login_url='common:login')
def url_edit(request,pk):
    if request.user.is_authenticated:
        surl = get_owned_surl(request, pk)
        if surl.domain.owner.username == request.user.username:
            if request.method == "POST":
                form = SurlForm(request.POST, instance=surl, user=request.user)
                if form.is_valid() :
                    surl = form.save(commit=False)
                    surl.domain = form.cleaned_data['domain']
                    surl.short_url = str(surl.domain.name)+"/"+(surl.alias)
                    try:
                        surl.validate_unique()
                        surl.save()
                        messages.success(request, f'URL {surl.short_url} was updated.')
                        return redirect('common:links')
                                        
                    except ValidationError as e:
                        domains, surls = get_owned_objects(request)
                        context = build_url_context(
                            domains=domains,
                            surls=surls,
                            dashboard_form=SurlForm(user=request.user, allow_blank_alias=True),
                            link_form=form,
                            e=e,
                            surl=surl,
                        )
                        messages.error(request, 'A link with the same domain and alias already exists.')
                        return render(request,'common/links.html',context=context)    
                    
            else:
                form = SurlForm(instance=surl, user=request.user)
                domains, surls = get_owned_objects(request)
                
                context = build_url_context(
                    domains=domains,
                    surls=surls,
                    dashboard_form=SurlForm(user=request.user, allow_blank_alias=True),
                    link_form=form,
                    surl=surl,
                )
                return render(request,'common/links.html',context=context)    
    
            return redirect('common:links')
            
        else:
            messages.error(request, 'Only links you own can be edited.')
            return render(request,'common/links.html')    

    return redirect('common:links')    


@login_required(login_url='common:login')
@require_POST
def domain_create(request):
    if request.user.is_authenticated:
        form = DomainForm(request.POST)
        active_tab = (request.POST.get('active_tab') or '').strip()
        if form.is_valid():
            domain = form.save(commit=False)
            domain.name = form.cleaned_data['name']
            domain.dns_txt = domain.create_dns_txt()
            domain.owner = request.user
            domain.host_allowed = False
            domain.save()
            redirect_path = append_tab_to_path(reverse('common:domain_list'), active_tab)
            redirect_path = append_query_params_to_path(redirect_path, created_domain=domain.pk)
            return redirect(redirect_path)

        domains, surls = get_owned_objects(request)
        context = {'domains': domains, 'form': form}
        return render(request, 'common/domain.html', context=context)

    return HttpResponse("login required")
    
@login_required(login_url='common:login')
@require_POST
def domain_verify(request,pk):
    if request.user.is_authenticated:
        domain = get_object_or_404(Domain, pk=pk)
        if domain.owner.username == request.user.username:
            redirect_target = append_tab_to_path(
                request.POST.get('next') or reverse('common:domain_settings', kwargs={'pk': domain.pk}),
                'domain-overview',
            )

            verification = domain.verify_ownership()
            if verification == 0:
                domain.is_verified = True
                domain.last_ownership_check = timezone.now()
                domain.dns_txt = None
                domain.save()

                if SSL_LIST:
                    with open(SSL_LIST, "a", encoding="utf-8") as f:
                        f.write(f"{domain.name}\n")

                messages.success(request, f'Domain ownership for {domain.name} was verified. Add the CNAME record next and run the CNAME status check.')
                return redirect(redirect_target)
            
            elif verification == 1:
                # retry, time limit
                to_retry=domain.last_ownership_check + timedelta(seconds=Domain.VERIFY_INTERVAL) - timezone.now()
                messages.error(request, f'Please try again in {to_retry.seconds:,} seconds.')
                return redirect(redirect_target)
                
            elif verification == 2:
                # TXT not found
                domain.last_ownership_check = timezone.now()
                err = 'The required DNS records could not be confirmed.'
                domain.last_ownership_check = timezone.now()
                domain.save()
                messages.error(request, err)
                return redirect(redirect_target)
        else:
            messages.error(request, 'Only domains you own can be verified.')
            return render(request, 'common/domain.html')     
                
    else:
        return HttpResponse("login required")
    
@login_required(login_url='common:login')
@require_POST
def domain_delete(request, pk):
    if request.user.is_authenticated:
        try:
            domain = Domain.objects.get(pk=pk)
            redirect_target = append_tab_to_path(
                request.POST.get('next') or reverse('common:domain_settings', kwargs={'pk': pk}),
                'domain-overview',
            )
            if domain.owner.username == request.user.username:
                password = (request.POST.get('confirm_password') or '').strip()
                if not password:
                    messages.error(request, 'Enter your current password to delete this domain.')
                    return redirect(redirect_target)
                if not request.user.check_password(password):
                    messages.error(request, 'The password you entered is incorrect.')
                    return redirect(redirect_target)
                domain.delete()
                messages.success(request, f'Domain {domain.name} was deleted.')
                return redirect('common:domain_list')

            messages.error(request, 'Only domains you own can be deleted.')
            return redirect(redirect_target)

        except Domain.DoesNotExist:
            messages.error(request, 'That domain does not exist.')
            return redirect('common:domain_list')

    return redirect('common:domain_list')

def page_not_found(request, exception):
    return render(request, 'common/404.html', {}, status=404)

def get_url_wc_data(surls):
    wc_data = []
    colors = []
    surls = list(surls)
    counts = [surl.visit_counts for surl in surls]
    max_count = max(counts) if counts else 0
    scale_base = max(max_count, 1)

    ranked_surls = sorted(surls, key=lambda surl: (-surl.visit_counts, surl.alias.lower()))

    for index, surl in enumerate(ranked_surls[:12], start=1):
        weight = round(surl.visit_counts / scale_base * 16) + 1
        wc_data.append({
            'rank': index,
            'alias': surl.alias,
            'weight': weight,
            'short_url': surl.short_url,
            'url': surl.url,
            'visit_counts': surl.visit_counts,
            'domain_name': surl.domain.name,
            'intensity': max(20, min(100, round(surl.visit_counts / scale_base * 100))),
        })

    return wc_data, colors

def recaptcha_result(request):
    if recaptcha_is_bypassed():
        return {'success': True, 'skipped': True}

    recaptcha_response = request.POST.get('g-recaptcha-response')
    if not recaptcha_response:
        return {'success': False, 'error-codes': ['missing-input-response']}

    if not settings.RECAPTCHA_SECRET:
        logger.warning('reCAPTCHA secret is not configured.')
        return {'success': False, 'error-codes': ['recaptcha-not-configured']}

    url = 'https://www.google.com/recaptcha/api/siteverify'
    values = {
        'secret': settings.RECAPTCHA_SECRET,
        'response': recaptcha_response,
    }
    data = urllib.parse.urlencode(values).encode()
    req = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning('reCAPTCHA verification failed: %s', exc)
        return {'success': False, 'error-codes': ['recaptcha-unavailable']}

    return result
