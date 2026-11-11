#!/usr/bin/env python3
"""Stands in for /usr/bin/open in tests: records its argv (FAKE_OPEN_LOG), opens nothing."""
import json
import os
import sys

with open(os.environ["FAKE_OPEN_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
sys.exit(int(os.environ.get("FAKE_OPEN_EXIT", "0")))
