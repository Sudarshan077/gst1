#!/usr/bin/env python3
import sys
import subprocess
import os

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
backend_path = os.path.join(root_path, 'backend')
os.environ['PYTHONPATH'] = backend_path

test_file = os.path.join(backend_path, "tests", "test_e2e_phase2.py")
result = subprocess.run(
    ["uv", "run", "--project", backend_path, "pytest", test_file],
    cwd=backend_path,
)
sys.exit(result.returncode)

