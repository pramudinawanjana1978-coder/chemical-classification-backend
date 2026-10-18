import os
import sys
import importlib.util

BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

API_FILE = os.path.join(BACKEND_DIR, "api.py")

spec = importlib.util.spec_from_file_location(
    "chemical_backend_app",
    API_FILE
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

app = module.app