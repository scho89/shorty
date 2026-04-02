from datetime import timedelta
from django.conf import settings 
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Count
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from common.forms import UserForm
from shorty.forms import SurlForm,DomainForm
from shorty.models import ClickEvent, Domain, Surl

import json
import logging
import sys
import urllib.parse
import urllib.request
from urllib.error import URLError


logger=logging.getLogger('shorty')
SSL_LIST = getattr(settings, 'SSL_LIST', '')
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


# Create your views here.
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
        return 'reCAPTCHA 설정이 누락되었습니다. 환경 변수를 확인하세요.'
    if 'recaptcha-unavailable' in error_codes:
        return 'reCAPTCHA 검증 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.'
    return 'reCAPTCHA가 완료되지 않았습니다. 확인 후 다시 시도하세요.'

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
                messages.success(request, '로그인 성공')
                login(request, user)
                return redirect('common:url')
            
            else:
                messages.error(request, '아이디 혹은 비밀번호가 올바르지 않습니다.')
                
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
                messages.success(request,"가입 완료")
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


def help_page(request):
    context = {
        'cname_target': '443.scho.kr',
    }
    return render(request, 'common/help.html', context)

@login_required(login_url='common:login')
def domain_list(request):
    
    # if request.method == "GET":
    if request.user.is_authenticated:
        domains = Domain.objects.filter(owner__username=request.user.username)
        context = {'domains':domains}
        return render(request,'common/domain.html',context=context)    

    else:
        return render(request,'shorty/index.html')    

@login_required(login_url='common:login')    
def url(request):
    if request.method == "GET":
        if request.user.is_authenticated:
            domains, surls = get_owned_objects(request)
            form = SurlForm(user=request.user)
            context = build_url_context(
                domains=domains,
                surls=surls,
                form=form,
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
        form = SurlForm(user=request.user)
        context = build_url_context(
            domains=domains,
            surls=surls,
            form=form,
            selected_domain_id=selected_domain_id,
            search_query=search_query,
        )
        return render(request, 'common/links.html', context=context)

    return redirect('common:links')

@login_required(login_url='common:login')
@require_POST
def url_create(request):
    if request.user.is_authenticated:
        form = SurlForm(request.POST, user=request.user)
        redirect_target = request.POST.get('next') or 'common:links'
        template_name = 'common/dashboard.html' if str(redirect_target).startswith('/_common_/url') else 'common/links.html'
        if form.is_valid():
            surl = form.save(commit=False)
            surl.domain = form.cleaned_data['domain']
            surl.short_url = str(surl.domain.name) + "/" + surl.alias
            try:
                surl.validate_unique()
                surl.save()
                messages.success(request, f"URL {surl.short_url}이 등록되었습니다.")
            except ValidationError as e:
                domains, surls = get_owned_objects(request)
                context = build_url_context(domains=domains, surls=surls, form=form, e=e)
                return render(request, template_name, context=context)
        else:
            domains, surls = get_owned_objects(request)
            context = build_url_context(domains=domains, surls=surls, form=form)
            return render(request, template_name, context=context)

        if redirect_target.startswith('/'):
            return redirect(redirect_target)
        return redirect(redirect_target)

    return HttpResponse('url created.')

def get_owned_objects(request):
    domains = Domain.objects.filter(owner=request.user).order_by('name')
    surls = Surl.objects.filter(domain__in=domains)
    surls = surls.order_by('-visit_counts')
    return domains, surls


def build_url_context(domains, surls, form, selected_domain_id='', search_query='', **extra):
    domains = list(domains)
    surls = list(surls)
    domain_badge_styles = get_domain_badge_styles(domains)

    for surl in surls:
        surl.domain_badge_style = domain_badge_styles.get(
            surl.domain.name,
            'background:#eff6ff;color:#1d4ed8;'
        )

    insights = get_url_insights(surls)

    context = {
        'surls': surls,
        'domains': domains,
        'form': form,
        'wc_data': insights['traffic_items'],
        'top_links': insights['top_links'],
        'rising_links': insights['rising_links'],
        'domain_trends': insights['domain_trends'],
        'selected_domain_id': str(selected_domain_id or ''),
        'search_query': search_query,
    }
    context.update(extra)
    return context


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


def build_top_links(surls):
    ranked = sorted(surls, key=lambda surl: (-surl.visit_counts, surl.alias.lower()))
    return [
        {
            'rank': index,
            'alias': surl.alias,
            'short_url': surl.short_url,
            'url': surl.url,
            'note': surl.note or 'No note',
            'visit_counts': surl.visit_counts,
            'domain_name': surl.domain.name,
        }
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

        rising.append({
            'alias': surl.alias,
            'short_url': surl.short_url,
            'url': surl.url,
            'note': surl.note or 'No note',
            'domain_name': surl.domain.name,
            'recent_total': recent_total,
            'previous_total': previous_total,
            'delta': delta,
        })

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

@login_required(login_url='common:login')
@require_POST
def url_delete(request,pk):
    if request.user.is_authenticated:
        surl = get_object_or_404(Surl, pk=pk)
        if surl.domain.owner.username == request.user.username:
            surl.delete()
            messages.success(request, f"URL {surl.short_url}이 삭제되었습니다.")
        else:
            messages.error(request, "내 소유의 주소만 삭제가 가능합니다.")
            return render(request,'common/links.html')

    return redirect('common:links')

@login_required(login_url='common:login')
def url_edit(request,pk):
    if request.user.is_authenticated:
        surl=Surl.objects.get(pk=pk)
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
                        messages.success(request,f"URL {surl.short_url}이 변경되었습니다.")
                        return redirect('common:links')
                                        
                    except ValidationError as e:
                        domains, surls = get_owned_objects(request)
                        context = build_url_context(domains=domains, surls=surls, form=form, e=e, surl=surl)
                        messages.error(request,"중복된 주소가 존재합니다.")
                        return render(request,'common/links.html',context=context)    
                    
            else:
                form = SurlForm(instance=surl, user=request.user)
                domains, surls = get_owned_objects(request)
                
                context = build_url_context(domains=domains, surls=surls, form=form, surl=surl)
                return render(request,'common/links.html',context=context)    
    
            return redirect('common:links')
            
        else:
            messages.error(request,"내 소유의 주소만 편집이 가능합니다.")
            return render(request,'common/links.html')    

    return redirect('common:links')    


@login_required(login_url='common:login')
@require_POST
def domain_create(request):
    if request.user.is_authenticated:
        form = DomainForm(request.POST)
        if form.is_valid():
            domain = form.save(commit=False)
            domain.name = form.cleaned_data['name']
            domain.dns_txt = domain.create_dns_txt()
            domain.owner = request.user
            domain.host_allowed = False
            domain.save()
            messages.success(request, f"도메인 {domain.name}이 등록되었습니다.")
            return redirect('common:domain_list')

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

            verification = domain.verify_ownership()
            if verification == 0:
                domain.is_verified = True
                domain.host_allowed = True
                domain.last_ownership_check = timezone.now()
                domain.dns_txt = None
                domain.save()

                if SSL_LIST:
                    with open(SSL_LIST, "a", encoding="utf-8") as f:
                        f.write(f"{domain.name}\n")

                messages.success(request, f"도메인 {domain.name}이 인증되었습니다.")
                return redirect('common:domain_list')
            
            elif verification == 1:
                # retry, time limit
                to_retry=domain.last_ownership_check + timedelta(seconds=Domain.VERIFY_INTERVAL) - timezone.now()
                messages.error(request,f"{to_retry.seconds:,}초 뒤에 다시 시도하세요.")
                domains = Domain.objects.filter(owner__username=request.user.username)
                context = {'domains':domains}
                
                return render(request, 'common/domain.html', context=context)
                
            elif verification == 2:
                # TXT not found
                domain.last_ownership_check = timezone.now()
                err = f"레코드를 확인할 수 없습니다."
                domains = Domain.objects.filter(owner__username=request.user.username)
                context = {'err':err, 'domains':domains}
                domain.last_ownership_check = timezone.now()
                domain.save()
                return render(request, 'common/domain.html', context=context)                
        else:
            messages.error(request,"내 소유의 도메인만 확인이 가능합니다.")
            return render(request, 'common/domain.html')     
                
    else:
        return HttpResponse("login required")
    
@login_required(login_url='common:login')
@require_POST
def domain_delete(request, pk):
    if request.user.is_authenticated:
        try:
            domain = Domain.objects.get(pk=pk)
            if domain.owner.username == request.user.username:
                domain.delete()
                messages.success(request, f"도메인 {domain.name}이 삭제되었습니다.")
                return redirect('common:domain_list')

            messages.error(request, "내 소유의 도메인만 삭제가 가능합니다.")
            return redirect('common:domain_list')

        except Domain.DoesNotExist:
            messages.error(request, "존재하지 않는 도메인입니다.")
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
