from django.db import models
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from dns.resolver import resolve

# Create your models here.

class Domain(models.Model):
    name = models.CharField(max_length=64,unique=True, primary_key=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
        

class Surl(models.Model):
    alias = models.CharField(max_length=128)
    url = models.URLField(max_length=2048)
    note = models.CharField(max_length=2048,blank=True)
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE)
    short_url = models.URLField(
        max_length=128,
        unique=True,
        error_messages={
            "unique": "단축 URL이 이미 존재합니다. Domain과 alias를 확인하십시오.",
        },)
    
    # def save(self, *args, **kwargs):
    #     self.short_url = str(self.domain)+"/"+(self.alias)
    #     super().save(*args, **kwargs)
    
    # @property
    # def short_url(self):
    #     return str(self.domain)+"/"+(self.alias)
    
    def __str__(self):
        return str(self.domain)+"/"+(self.alias)

    def validation(self,short_url):
        try: 
            self.objects.get(short_url=short_url)
            return False
        except self.DoesNotExist:
            return True 
            
