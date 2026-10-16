"""退出码常量与领域异常。

退出码语义（K2，定稿后锁进 tests/test_cli_contract.py，后续重构不漂移）：

    0  成功完成
    1  完成但有降级 / 检出问题（如部分频道抓取失败、基准未达标）
    2  用法错误 / 输入不可用（未知子命令、参数错、输入文件缺失、坏格式）
    3  能力未就绪（骨架期专用；模块落地后整项退役）
    4  外部依赖不可用（网络不可达、API 返回非 200、API 结构异常）

退出码 3 的退役流程（四处同步，少一处即幽灵语义复活）：
删常量 -> 改 CLI/退出码/selftest 测试（含 `not hasattr` 防复活）-> 改 README 退出码表
-> 改 plan/00 决策记录。
"""

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_USAGE = 2
EXIT_NOT_READY = 3
EXIT_EXTERNAL = 4

#: 全部合法退出码（selftest 断言齐备性用）。
ALL_EXIT_CODES = (EXIT_OK, EXIT_DEGRADED, EXIT_USAGE, EXIT_NOT_READY, EXIT_EXTERNAL)


class RadarError(ValueError):
    """本领域全部异常的基类。

    **必须继承 ValueError**（不是裸 `Exception`）：CLI 的 `except (RadarError, ValueError)`
    才能捕获它并转成既定退出码。若继承裸 Exception，异常会逃逸成未捕获 traceback——
    用户看到"程序崩了"而不是"输入有问题，退出码 2"，而单元测试可能全绿（测试直接调函数、
    断言它抛出，看不到 CLI 层的逃逸）。
    """

    #: 该异常对应的 CLI 退出码，由 CLI 层读取（机读字段）。
    code = EXIT_USAGE

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class UsageError(RadarError):
    """用法错误 / 输入不可用 -> exit 2。"""

    code = EXIT_USAGE


class NotReadyError(RadarError):
    """能力未就绪（骨架期专用）-> exit 3。不伪造空结果。"""

    code = EXIT_NOT_READY


class ExternalError(RadarError):
    """外部依赖不可用（网络/API）-> exit 4。"""

    code = EXIT_EXTERNAL


class DegradedError(RadarError):
    """完成但有降级 -> exit 1。"""

    code = EXIT_DEGRADED
