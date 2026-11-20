"""WSGI entry point for AWS Elastic Beanstalk.

Elastic Beanstalk's Python platform looks for an application callable.
The CampusQuest Flask instance is named `app` in app.py.
"""
from app import app as application
