#!/usr/bin/env python3
import sys
import subprocess
import os

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
backend_path = os.path.join(root_path, 'backend')
os.environ['PYTHONPATH'] = root_path

test_files = [
    os.path.join(backend_path, "tests", "test_gsp.py"),
    os.path.join(backend_path, "tests", "test_irp_live_gated.py")
]
result = subprocess.run(
    ["uv", "run", "--project", backend_path, "pytest", "--no-cov"] + test_files,
    cwd=backend_path,
)
sys.exit(result.returncode)
