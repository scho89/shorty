from .base import *
import environ
import logging
import pymssql

logger = logging.getLogger('shorty')

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

ALLOWED_HOSTS = list(dict.fromkeys(env.list('ALLOWED_HOSTS', default=[])))
DEBUG = env.bool('DEBUG', default=False)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)

try:
    conn = pymssql.connect(
        server=env('DB_HOST'),
        user=env('DB_USER'),
        password=env('DB_PASSWORD'),
        database=env('DB_NAME'),
        port=env.int('DB_PORT', default=1433),
        charset='utf8',
        login_timeout=5,
        timeout=5,
    )
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM shorty_domain WHERE host_allowed='TRUE';")

    row = cursor.fetchone()
    while row:
        ALLOWED_HOSTS.append(row[0])
        row = cursor.fetchone()

    conn.close()
except Exception as exc:
    logger.warning('Could not load host_allowed domains from MSSQL during startup: %s', exc)

if env.bool('ALLOW_LOCAL_HOSTS', default=False):
    for host in ['127.0.0.1', 'localhost']:
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)

ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))

if not env.list('CSRF_TRUSTED_ORIGINS', default=[]):
    csrf_hosts = []
    for host in ALLOWED_HOSTS:
        normalized = host.strip()
        if not normalized or normalized in {'127.0.0.1', 'localhost'}:
            continue
        if normalized.startswith('.'):
            normalized = normalized.lstrip('.')
        if ':' in normalized:
            continue
        csrf_hosts.append(f'https://{normalized}')
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(csrf_hosts))

#
#DATABASES ={
#    'default' : {
#        'ENGINE' : 'django.db.backends.postgresql_psycopg2',
#        'NAME' : env('DB_NAME'),
#        'USER' : env('DB_USER'),
#        'PASSWORD': env('DB_PASSWORD'),
#        'HOST': env('DB_HOST'),
#        'PORT': '5432',
#    }
#}


DATABASES ={
    'default' : {
        'ENGINE' : 'mssql',
        'NAME' : env('DB_NAME'),
        'USER' : env('DB_USER'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST'),
        'PORT': env('DB_PORT'),
		'OPTIONS': {'driver': 'ODBC Driver 17 for SQL Server'},
    }
}

