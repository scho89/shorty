from .base import *
import environ
import pymssql

ALLOWED_HOSTS = []
STATIC_ROOT = BASE_DIR / 'static/'
STATICFILES_DIRS = []
DEBUG = False

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

conn = pymssql.connect(host=env('DB_HOST'), database=env('DB_NAME'), charset='utf8',user=env('DB_USER'),password=env('DB_PASSWORD'))
cursor = conn.cursor()
cursor.execute("SELECT * FROM shorty_domain WHERE host_allowed='TRUE';")

row = cursor.fetchone()
while row:
    ALLOWED_HOSTS.append(row[1])
    row = cursor.fetchone()

conn.close()

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

