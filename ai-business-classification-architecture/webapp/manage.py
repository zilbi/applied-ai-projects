#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'src'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','fintech_portal.settings')
from django.core.management import execute_from_command_line
if __name__=='__main__': execute_from_command_line(sys.argv)
