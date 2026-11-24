"""模拟会谈评分的组合异常诊断与成绩复核工具。

按轮次复用：读取考务交换包，完成交叉结构检查、分歧诊断、
复听名额安排与成绩通知状态管理。各表口径见 data-contract.md。
"""

__all__ = [
    "bundle",
    "scale",
    "structure",
    "models",
    "risk",
    "panel",
    "notify",
    "report",
]
