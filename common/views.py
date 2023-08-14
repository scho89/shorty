from datetime import timedelta
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from django.utils import timezone
from common.forms import UserForm
from shorty.forms import SurlForm,DomainForm
from shorty.models import Domain,Surl
from pathlib import Path
from random import randint,shuffle
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')
SSL_LIST = env('SSL_LIST')

# Create your views here.


def signup(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)
            return redirect('common:url')
    else:
        form = UserForm()
        
    return render(request, 'common/signup.html', {'form':form})


def page_not_found(request, exception):
    return render(request, 'common/404.html', {})

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
            domains,surls = get_owned_objects(request)
            form = SurlForm()
            
            # get wc data
            wc_data = get_url_wc_data(surls)
            print(wc_data)
            # print(colors)
                                    
            context = {'surls':surls,'domains':domains, 'form':form, 'wc_data':wc_data} #, 'colors':colors}
            return render(request,'common/url.html',context=context)    

        else:
            return render(request,'common/url.html')    

@login_required(login_url='common:login')    
def url_create(request):
    
    if request.user.is_authenticated:
        if request.method == "POST":
            form = SurlForm(request.POST)
            print(form)
            if form.is_valid() :
                print('form is valid')
                surl = form.save(commit=False)
                surl.domain = Domain.objects.get(name=form.cleaned_data['domain'])
                surl.short_url = str(surl.domain.name)+"/"+(surl.alias)
                try:
                    surl.validate_unique()
                    surl.save()
                                    
                except ValidationError as e:
                    domains, surls = get_owned_objects(request)
                    context = {'surls':surls,'domains':domains, 'form':form, 'e':e}
                    return render(request,'common/url.html',context=context)    
                
            else:
                domains, surls = get_owned_objects(request)
                context = {'surls':surls,'domains':domains, 'form':form}
                return render(request,'common/url.html',context=context)    
   
        return redirect('common:url')
    
    return HttpResponse('url created.')

def get_owned_objects(request):
    domains = Domain.objects.filter(owner__username=request.user.username)
    print(domains)
    surls = Surl.objects.filter(domain__in=domains)
    print(surls)
    return domains,surls

@login_required(login_url='common:login')
def url_delete(request,pk):
    
    if request.user.is_authenticated:
        surl=Surl.objects.get(pk=pk)
        if surl.domain.owner.username == request.user.username:
            # 소유 여부 추가
            surl.delete()
            
        else:
            err = Serr("내 소유의 주소만 삭제가 가능합니다.", 403)
            context={'err':err}
            return render(request, 'common/error.html', context=context)

    return redirect('common:url')

@login_required(login_url='common:login')
def domain_create(request):
    
    if request.user.is_authenticated:
        if request.method == "POST":
            form = DomainForm(request.POST)
            print(form)
            if form.is_valid() :
                print('form is valid')
                domain = form.save(commit=False)
                domain.name = form.cleaned_data['name']
                domain.dns_txt = domain.create_dns_txt()
                domain.owner = request.user
                domain.host_allowed = False
                domain.save()
                return redirect('common:domain_list')
                                    
            else:
                domains, surls = get_owned_objects(request)
                context = {'domains':domains, 'form':form}
                return render(request,'common/domain.html',context=context)    
    
    else:
        return HttpResponse("login required")
    
@login_required(login_url='common:login')
def domain_verify(request,pk):
    if request.user.is_authenticated:
        domain = Domain.objects.get(pk=pk)
        if domain.owner.username == request.user.username:

            verification = domain.verify_ownership()
            if verification == 0:
                domain.is_verified = True
                domain.last_ownership_check = timezone.now()
                domain.dns_txt = None
                domain.save()
                
                with open(SSL_LIST, "a") as f:
                    f.write(f"{domain.name}\n")
                                
                return redirect('common:domain_list')
            
            elif verification == 1:
                # retry, time limit
                print(domain.VERIFY_INTERVAL)

                to_retry=domain.last_ownership_check + timedelta(seconds=Domain.VERIFY_INTERVAL) - timezone.now()
                err = f"{to_retry.seconds:,}초 뒤에 다시 시도하세요."
                domains = Domain.objects.filter(owner__username=request.user.username)
                context = {'err':err,'domains':domains}
                
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
            err = Serr("내 소유의 도메인만 확인이 가능합니다.", 403)
            context = {'err':err}
            return render(request, 'common/domain.html', context=context)     
                
    else:
        return HttpResponse("login required")
    
@login_required(login_url='common:login')
def domain_delete(request, pk):
    
    if request.user.is_authenticated:
        domain = Domain.objects.get(pk=pk)
        if domain.owner.username == request.user.username:
            domain.delete()
            domains = Domain.objects.filter(owner__username=request.user.username)
            context = {'domains':domains}
            return render(request, 'common/domain.html', context=context)    
                                    
        else:
            err = Serr("내 소유의 도메인만 삭제가 가능합니다.", 403)
            context={'err':err}
            return render(request, 'common/error.html', context=context)
    
    else:
        return HttpResponse("login required")

def page_not_found(request, exception):
    return render(request, 'common/404.html', {})

def get_url_wc_data(surls):
    wc_data = []
    counts = []
    # colors = []
    # total = 0
    
    for surl in surls:
        counts.append(surl.visit_counts)
        #total += surl.visit_counts
    
    if max(counts) == 0:
        counts.append(1)
    
    for surl in surls:
        data = {}
        data['alias'] = surl.alias
        data['weight'] = round(surl.visit_counts/max(counts)*16)+1
        data['color'] = "#"+hex(randint(50,255))[2:]+hex(randint(50,255))[2:]+hex(randint(50,255))[2:]
        data['short_url'] = surl.short_url
        wc_data.append(data)
        
    # for i in range(1,18):
    #     colors.append("#"+hex(randint(50,255))[2:]+hex(randint(50,255))[2:]+hex(randint(50,255))[2:])
    
    shuffle(wc_data)
    
    return wc_data#,colors
         
class Serr:
    message = None
    code = None
    
    def __init__(self, message, code):
        self.message = message
        self.code = code