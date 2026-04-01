import os

profile = os.getenv('DJANGO_SETTINGS_PROFILE', 'local').lower()

if profile in {'prod', 'production'}:
    from .prod import *
else:
    from .local import *
