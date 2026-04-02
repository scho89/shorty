from django.db.models import F
from django.shortcuts import redirect
from shorty.models import ClickEvent, Surl

import logging

logger = logging.getLogger('shorty')

# Create your views here.


def index(request):
    return redirect('common:url')
    
    # # if request.method == "GET":
    # if request.user.is_authenticated:
    #     surls = Surl.objects.filter(owner__username=request.user.username)
    #     context = {'surls':surls}
    #     return render(request,'shorty/index.html',context=context)    

    # else:
    #     return render(request,'shorty/index.html')    

def surl(request,alias):
    domain = request.get_host().split(':')[0]

    try:
        surl = Surl.objects.only('id', 'url').get(domain__name=domain, alias=alias)
    except Surl.DoesNotExist:
        return redirect('common:url')

    Surl.objects.filter(pk=surl.pk).update(visit_counts=F('visit_counts') + 1)
    ClickEvent.objects.create(surl_id=surl.pk)
    return redirect(surl.url)
