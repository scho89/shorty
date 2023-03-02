from django.shortcuts import render, HttpResponse

# Create your views here.


def _admin(request):
    return HttpResponse('Admin page')