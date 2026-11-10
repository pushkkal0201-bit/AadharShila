"""Shared deployment boundary.

Only explicit local development/test modes permit demonstration credentials and
research preview. Every other environment is restricted, regardless of case.
"""
import os


def is_production() -> bool:
    return os.getenv('APP_ENV', 'development').strip().casefold() not in {'development', 'test'}
