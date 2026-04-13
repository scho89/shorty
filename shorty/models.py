from datetime import timedelta
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.crypto import get_random_string
from dns.exception import DNSException
from dns.resolver import NoAnswer, Resolver


def get_dns_resolver():
    nameservers = [
        str(nameserver).strip()
        for nameserver in getattr(settings, 'DNS_RESOLVER_NAMESERVERS', [])
        if str(nameserver).strip()
    ]
    if not nameservers:
        return Resolver()

    resolver = Resolver(configure=False)
    resolver.nameservers = nameservers
    return resolver


def resolve_dns(name, record_type):
    return get_dns_resolver().resolve(name, record_type)

# Create your models here.

class Domain(models.Model):
    POLICY_ACTION_INHERIT = 'inherit'
    ROOT_ACTION_DASHBOARD = 'dashboard'
    ROOT_ACTION_FALLBACK = 'fallback'
    ROOT_ACTION_SHOW_MESSAGE = 'show_message'
    ROOT_ACTION_INHERIT = POLICY_ACTION_INHERIT
    MESSAGE_ACTION = 'message'
    POLICY_ACTION_CHOICES = [
        (POLICY_ACTION_INHERIT, 'Use global default'),
        (ROOT_ACTION_FALLBACK, 'Redirect to fallback URL'),
        (MESSAGE_ACTION, 'Show message'),
    ]
    ROOT_ACTION_CHOICES = [
        (ROOT_ACTION_INHERIT, 'Use global default'),
        (ROOT_ACTION_DASHBOARD, 'Open Shorty dashboard'),
        (ROOT_ACTION_FALLBACK, 'Redirect to registered fallback URL'),
        (ROOT_ACTION_SHOW_MESSAGE, 'Show message page'),
    ]

    name = models.CharField(max_length=64)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    is_verified = models.BooleanField(default=False)
    dns_txt = models.CharField(max_length=50,null=True,blank=True)
    last_ownership_check = models.DateTimeField(null=True,blank=True)
    host_allowed = models.BooleanField(default=False)
    root_action = models.CharField(
        max_length=32,
        choices=ROOT_ACTION_CHOICES,
        default=ROOT_ACTION_INHERIT,
    )
    root_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='domain_root_fallbacks',
    )
    root_message = models.CharField(max_length=255, blank=True)
    missing_alias_action = models.CharField(
        max_length=32,
        choices=POLICY_ACTION_CHOICES,
        default=POLICY_ACTION_INHERIT,
    )
    missing_alias_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='domain_missing_alias_fallbacks',
    )
    missing_alias_message = models.CharField(max_length=255, blank=True)
    inactive_action = models.CharField(
        max_length=32,
        choices=POLICY_ACTION_CHOICES,
        default=POLICY_ACTION_INHERIT,
    )
    inactive_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='domain_inactive_fallbacks',
    )
    inactive_message = models.CharField(max_length=255, blank=True)
    expired_action = models.CharField(
        max_length=32,
        choices=POLICY_ACTION_CHOICES,
        default=POLICY_ACTION_INHERIT,
    )
    expired_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='domain_expired_fallbacks',
    )
    expired_message = models.CharField(max_length=255, blank=True)
    
    VERIFY_INTERVAL = 5

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return f'https://{self.name}/'
    
    def create_dns_txt(self):
        return "shorty-"+get_random_string(length=30)

    @staticmethod
    def normalize_dns_value(value):
        return (value or '').strip().rstrip('.').lower()

    @classmethod
    def get_expected_cname_target(cls):
        return cls.normalize_dns_value(getattr(settings, 'CNAME_HOST_TARGET', ''))

    def get_cname_status(self):
        expected_target = self.get_expected_cname_target()
        status = {
            'configured': bool(expected_target),
            'expected_target': expected_target,
            'resolved_targets': [],
            'matches': False,
        }

        if not expected_target:
            return status

        try:
            answers_cname = resolve_dns(self.name, 'CNAME')
        except (NoAnswer, DNSException):
            return status

        resolved_targets = [
            normalized
            for normalized in (self.normalize_dns_value(answer.to_text()) for answer in answers_cname)
            if normalized
        ]
        status['resolved_targets'] = resolved_targets
        status['matches'] = expected_target in resolved_targets
        return status
    
    def verify_ownership(self):
        # code 0: confirmed
        # code 1: retry after 5 minutes
        # code 2: not verified
        if self.last_ownership_check and timezone.now() - self.last_ownership_check < timedelta(seconds=self.VERIFY_INTERVAL):
            return 1

        try:
            answers_txt = resolve_dns(self.name, 'TXT')
        except (NoAnswer, DNSException):
            return 2

        for answer in answers_txt:
            if self.dns_txt and self.dns_txt in answer.to_text():
                return 0
        return 2
    
    # def save(self, *args, **kwargs):
    #     self.short_url = str(self.domain)+"/"+(self.alias)
    #     super().save(*args, **kwargs)

class Surl(models.Model):
    alias = models.CharField(max_length=128)
    url = models.URLField(max_length=2048)
    note = models.CharField(max_length=2048,blank=True)
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    short_url = models.URLField(
        max_length=128,
        unique=True,
        error_messages={
            "unique": "That short URL already exists. Check the domain and alias.",
        },)
    visit_counts = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['domain', 'alias'], name='shorty_surl_domain_alias_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['domain', 'alias'], name='shorty_unique_alias_per_domain'),
        ]
    
    # def save(self, *args, **kwargs):
    #     self.short_url = str(self.domain)+"/"+(self.alias)
    #     super().save(*args, **kwargs)
    
    # @property
    # def short_url(self):
    #     return str(self.domain)+"/"+(self.alias)
    
    def __str__(self):
        return str(self.domain)+"/"+(self.alias)

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def is_available(self):
        return self.is_active and not self.is_expired

    def validation(self,short_url):
        try: 
            self.objects.get(short_url=short_url)
            return False
        except self.DoesNotExist:
            return True 


class ClickEvent(models.Model):
    surl = models.ForeignKey(Surl, on_delete=models.CASCADE, related_name='click_events')
    referrer = models.URLField(max_length=2048, blank=True)
    browser = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['surl', 'created_at'], name='shorty_click_surl_created_idx'),
        ]


class FallbackDestination(models.Model):
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=2048)
    note = models.CharField(max_length=255, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'name'], name='shorty_unique_fallback_name_per_owner'),
        ]

    def __str__(self):
        return f'{self.name} -> {self.url}'


class GlobalRoutingSettings(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='global_routing_settings')
    root_action = models.CharField(
        max_length=32,
        choices=[
            (Domain.ROOT_ACTION_DASHBOARD, 'Open Shorty dashboard'),
            (Domain.ROOT_ACTION_FALLBACK, 'Redirect to fallback URL'),
            (Domain.ROOT_ACTION_SHOW_MESSAGE, 'Show message'),
        ],
        default=Domain.ROOT_ACTION_DASHBOARD,
    )
    root_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='global_root_fallbacks',
    )
    root_message = models.CharField(max_length=255, blank=True)
    missing_alias_action = models.CharField(
        max_length=32,
        choices=[
            (Domain.ROOT_ACTION_FALLBACK, 'Redirect to fallback URL'),
            (Domain.MESSAGE_ACTION, 'Show message'),
        ],
        default=Domain.MESSAGE_ACTION,
    )
    missing_alias_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='global_missing_alias_fallbacks',
    )
    missing_alias_message = models.CharField(max_length=255, blank=True)
    inactive_action = models.CharField(
        max_length=32,
        choices=[
            (Domain.ROOT_ACTION_FALLBACK, 'Redirect to fallback URL'),
            (Domain.MESSAGE_ACTION, 'Show message'),
        ],
        default=Domain.MESSAGE_ACTION,
    )
    inactive_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='global_inactive_fallbacks',
    )
    inactive_message = models.CharField(max_length=255, blank=True)
    expired_action = models.CharField(
        max_length=32,
        choices=[
            (Domain.ROOT_ACTION_FALLBACK, 'Redirect to fallback URL'),
            (Domain.MESSAGE_ACTION, 'Show message'),
        ],
        default=Domain.MESSAGE_ACTION,
    )
    expired_fallback = models.ForeignKey(
        'FallbackDestination',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='global_expired_fallbacks',
    )
    expired_message = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f'Global routing settings for {self.owner}'
