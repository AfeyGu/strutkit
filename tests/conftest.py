"""让测试不用安装也能 import strutkit（把项目根加入搜索路径），
并把 examples 目录加入路径，让测试能复用示例里的 build()。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)                 # strutkit/
_ROOT = os.path.dirname(_PKG)                 # 项目根
_EXAMPLES = os.path.join(_PKG, "examples")

for _p in (_ROOT, _EXAMPLES):
    if _p not in sys.path:
        sys.path.insert(0, _p)
