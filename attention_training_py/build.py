#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""?????????? dynamic_build.py?????????"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dynamic_build import main

if __name__ == "__main__":
    main()
