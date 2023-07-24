import environ
from .base import *

ALLOWED_HOSTS = ['*']
STATIC_ROOT = BASE_DIR / 'static/'
STATICFILES_DIRS = []
DEBUG = False

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

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

