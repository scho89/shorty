from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.crypto import get_random_string
from dns.resolver import resolve,NoAnswer

# Create your models here.

class Domain(models.Model):
    name = models.CharField(max_length=64)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    is_verified = models.BooleanField(default=False)
    dns_txt = models.CharField(max_length=50,null=True,blank=True)
    last_ownership_check = models.DateTimeField(null=True,blank=True)
    host_allowed = models.BooleanField(default=False)
    
    VERIFY_INTERVAL = 5

    def __str__(self):
        return self.name
    
    def create_dns_txt(self):
        return "shorty-"+get_random_string(length=30)
    
    def verify_ownership(self):
        # code 0: confirmed
        # code 1: retry after 5 minutes
        # code 2: not verified
        if (not self.last_ownership_check) or self.last_ownership_check - timezone.now() < timedelta(seconds=self.VERIFY_INTERVAL):
            try: 
                answers_txt = resolve(self.name,'TXT')
                answers_cname = resolve(self.name, 'CNAME')
            except NoAnswer:
                return 2
                
            for answer in answers_txt:
                if self.dns_txt in answer.to_text():
                    for answer in answers_cname:
                        if '443.scho.kr' in answer.to_text():
                            return 0
            return 2
        return 1    
    
    # def save(self, *args, **kwargs):
    #     self.short_url = str(self.domain)+"/"+(self.alias)
    #     super().save(*args, **kwargs)

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
            
