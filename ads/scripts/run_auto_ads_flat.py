#!/usr/bin/env python3
"""Flat runner: invoke the HermesVPN poster ads script (auto_ads.py) directly."""
import os
import subprocess
import sys

SCRIPT = "/root/.hermes/ads/scripts/auto_ads.py"
PYS = sorted(__import__("glob").glob("/root/.hermes/tools/python*/bin/python3"))[-1]

if not os.path.exists(SCRIPT):
    print("MISSING_SCRIPT", SCRIPT)
    sys.exit(2)

r = subprocess.run([PYS, SCRIPT], capture_output=True, text=True)
print("rc=", r.returncode)
print("--- stdout ---")
print(r.stdout)
print("--- stderr ---")
print(r.stderr[-4000:])
