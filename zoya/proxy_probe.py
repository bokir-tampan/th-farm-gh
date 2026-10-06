#!/usr/bin/env python3
"""Probe format PROXY_LIST (redacted) + tes reachability zoyalink lewat proxy."""
import os, re
raw = os.environ.get("PROXY_LIST", "")
lines = [l.strip() for l in raw.splitlines() if l.strip()]
print("total:", len(lines))
for l in lines[:5]:
    red = re.sub(r'//[^@]+@', '//***@', l)
    red = re.sub(r'\d{1,3}(\.\d{1,3}){3}', 'IP', red)
    print(" sample:", red, "| has_scheme=", "://" in l, "| has_auth=", "@" in l)
