"""
Main entry point for running the app as a module: python -m app
This allows proper module resolution when running via: python -m app.server
"""
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.server import *
