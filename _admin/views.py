from django.shortcuts import render, HttpResponse
from shorty.models import Surl

# Create your views here.


def _admin(request):
    
    print('_admin')
    surls = Surl.objects.filter(owner__username=request.user.username)
   
    context = {'surls':surls}
    
    return render(request, '_admin/home.html',context=context)



# domain verification - get
# add domain
# add alias
