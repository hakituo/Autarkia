#!/usr/bin/env python3
"""``python -m scripts.sync.env_sync`` 的入口：转发到门面 main()。"""

import sys

from scripts.sync.env_sync import main

if __name__ == "__main__":
    sys.exit(main())
