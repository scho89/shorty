from django.db import models
from django.contrib.auth.models import User

# Create your models here.

class Domain(models.Model):
    name = models.CharField(max_length=64)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

class Surl(models.Model):
    alias = models.CharField(max_length=128,unique=True)
    url = models.URLField(max_length=2048)
    note = models.CharField(max_length=2048,blank=True)
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    

    