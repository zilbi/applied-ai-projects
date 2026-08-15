from __future__ import annotations
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = ROOT
def env_file() -> None:
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1); os.environ.setdefault(key.strip(),value.strip())
env_file()
SECRET_KEY=os.environ.get('DJANGO_SECRET_KEY') or secrets.token_urlsafe(32)
DEBUG=os.environ.get('DJANGO_DEBUG','true').lower()=='true'
ALLOWED_HOSTS=[x.strip() for x in os.environ.get('DJANGO_ALLOWED_HOSTS','127.0.0.1,localhost').split(',') if x.strip()]
INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','classifier_ui']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF='fintech_portal.urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION='fintech_portal.wsgi.application'
def rooted(value: str) -> Path:
    path=Path(value); return path if path.is_absolute() else ROOT/path
_db_path=rooted(os.environ.get('DJANGO_DB_PATH','results/webapp/webapp.sqlite3')); _db_path.parent.mkdir(parents=True,exist_ok=True)
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':str(_db_path)}}
LANGUAGE_CODE='en-us'; TIME_ZONE='Europe/Moscow'; USE_I18N=True; USE_TZ=True
STATIC_URL='/static/'; STATIC_ROOT=str(ROOT/'results/webapp/static')
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
MAX_UPLOAD_MB=int(os.environ.get('DJANGO_MAX_UPLOAD_MB','50')); FILE_UPLOAD_MAX_MEMORY_SIZE=MAX_UPLOAD_MB*1024*1024
UPLOAD_DIR=rooted(os.environ.get('DJANGO_UPLOAD_DIR','results/webapp/uploads')); PIPELINE_RESULTS_DIR=rooted(os.environ.get('PIPELINE_RESULTS_DIR','results/runs'))
