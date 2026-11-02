"""让测试不用安装也能 import strutkit（把仓库根加入搜索路径），
并把 examples 目录加入路径，让测试能复用示例里的 build()。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)                 # 仓库根（strutkit/ 包的上一级）
_EXAMPLES = os.path.join(_ROOT, "examples")

for _p in (_ROOT, _EXAMPLES):
    if _p not in sys.path:
        sys.path.insert(0, _p)
