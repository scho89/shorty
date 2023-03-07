from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from common.forms import UserForm
from shorty.forms import SurlForm
from shorty.models import Domain,Surl

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
def domain(request):
    
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
            context = {'surls':surls,'domains':domains, 'form':form}
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
                surl.domain = Domain.objects.get(pk=form.cleaned_data['domain'])
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
   
        return render(request, 'common/url.html')
    
    return HttpResponse('url created.')

def get_owned_objects(request):
    domains = Domain.objects.filter(owner__username=request.user.username)
    surls = Surl.objects.filter(domain__name__in=domains)
    return domains,surls

@login_required(login_url='common:login')
def url_delete(request,pk):
    if request.user.is_authenticated:
        surl=Surl.objects.get(pk=pk)
        surl.delete()

    return redirect('common:url')