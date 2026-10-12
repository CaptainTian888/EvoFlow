"""pytest 收集开关：隔离本目录下的手工 demo 脚本。

``test_new_search.py`` 不是单元测试，而是一段手工演示脚本（打印 emoji 横幅、
硬编码 ``query="国华人寿"``）。它位于源码包内，却用 ``sys.path.insert`` 把本目录
提升为顶层，导致 ``tools.py`` 的相对导入 ``from .news_53ai_frontier import ...``
失去父包而报 ``ImportError: attempted relative import with no known parent package``，
每次收集阶段都中断。

这里只把该手工脚本排除出收集，不改动其内容、不删除。真正的包导入
（``from .tools import web_search_tool``）在 ``__init__.py`` 里仍然正常。
"""

collect_ignore = ["test_new_search.py"]
