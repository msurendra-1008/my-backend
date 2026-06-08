#!/usr/bin/env bash
set -e  # Exit on any error

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate