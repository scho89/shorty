import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
environ.Env.read_env(BASE_DIR / '.env')

profile = os.getenv('DJANGO_SETTINGS_PROFILE', 'local').lower()

if profile in {'prod', 'production'}:
    from .prod import *
else:
    from .local import *
