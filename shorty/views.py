from django.shortcuts import render,redirect
from django.db.models import Q
from django.http import HttpResponse
from shorty.models import Surl

# Create your views here.


def index(request):
    
    if request.user.is_authenticated:
        surls = Surl.objects.filter(owner__username=request.user.username)
        print(surls)
        return HttpResponse(f"Hello, {request.user.username}")    

    else:
        return HttpResponse('Hello, AnonymousUser')

def surl(request,alias):
    domain=(request.get_host()).split(':')[0]

    try:
        surl = Surl.objects.get(alias=alias)
    except Surl.DoesNotExist:
        surl = False
    
    if surl:
        return redirect(surl.url)
    
    return HttpResponse(alias)