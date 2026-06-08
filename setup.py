#!/usr/bin/env python3
"""
Setup script for AI Visual Assistant.

This is a minimal setup.py for backwards compatibility.
All metadata is now declared in pyproject.toml (the modern standard).

You can still do:
    python setup.py install
    python setup.py develop
    pip install -e .

But `pip install -e .` (or `pip install -e ".[fast]"`) is recommended.
"""

from setuptools import setup

if __name__ == "__main__":
    setup()