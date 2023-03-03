from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect, HttpResponse
from common.forms import UserForm
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
            return redirect('index')
    else:
        form = UserForm()
        
    return render(request, 'common/signup.html', {'form':form})


def page_not_found(request, exception):
    return render(request, 'common/404.html', {})


def domain(request):
    
    # if request.method == "GET":
    if request.user.is_authenticated:
        domains = Domain.objects.filter(owner__username=request.user.username)
        context = {'domains':domains}
        return render(request,'common/domain.html',context=context)    

    else:
        return render(request,'shorty/index.html')    
    
def url(request):
    
    # if request.method == "GET":
    if request.user.is_authenticated:
        surls = Surl.objects.filter(owner__username=request.user.username)
        domains = Domain.objects.filter(owner__username=request.user.username)
        context = {'surls':surls,'domains':domains}
        return render(request,'common/url.html',context=context)    

    else:
        return render(request,'common/url.html')    
    
def url_create(request):
    
    return HttpResponse('url created.')