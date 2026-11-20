#!/usr/bin/env python
"""Django's command-line utility (also puts ./vendor, where dependencies are installed for AppSail, on the path)."""
import os
import sys
from pathlib import Path


def main():
    vendor = Path(__file__).resolve().parent / 'vendor'
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apex.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
