#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 运行主程序
if __name__ == "__main__":
    from main import main
    main()
