"""按登记的批次风险规则划分评分单元。

每条规则针对一个 年级×分项 批次，对每位评分员在该批次的
剧本调整偏差作判定：

- ``exceeds``：置信区间整体越出 ±max_bias，确认越界——可疑单元，
  锁定并走替代分/裁决；
- ``suspect``：点估计越出 ±max_bias 但区间跨界，证据不足定论——
  先锁住，安排定向复听（考务不能因一张异常榜就扣分，也不能
  无证据放行）；
- ``cleared``：点估计落在界限内——可正常查分，区间一并公示；
- ``undetermined_lack_of_crossings``：交叉数不足 min_crossings——
  只能保留疑问，不据以锁分。

锁定只覆盖该评分员在该年级批次内实际评分的场次与分项，
同一位评分员的其他场次不一并判无效。
"""
from collections import defaultdict

from scipy import stats

VERDICT_EXCEEDS = "exceeds"
VERDICT_SUSPECT = "suspect"
VERDICT_CLEARED = "cleared"
VERDICT_UNDETERMINED = "undetermined_lack_of_crossings"

LOCKED_VERDICTS = (VERDICT_EXCEEDS, VERDICT_SUSPECT)


def evaluate_rules(bundle, edition, diagnosis, pair_map):
    """对每条风险规则逐评分员判定，返回单元判定清单。"""
    cells_by_item = {item: diagnosis[item]["cells"] for item in diagnosis}
    fits = {item: diagnosis[item]["two_way"] for item in diagnosis}
    verdicts = []
    for rule in sorted(bundle.risk_rules, key=lambda r: (r.priority, r.cohort, r.item)):
        cells = cells_by_item.get(rule.item, {})
        fit = fits.get(rule.item)
        raters = sorted({key.split("|")[0] for key in cells})
        for rater in raters:
            cell = cells.get(f"{rater}|{rule.cohort}")
            base = {
                "cohort": rule.cohort,
                "item": rule.item,
                "rater": rater,
                "max_bias": rule.max_bias,
                "confidence": rule.confidence,
                "min_crossings": rule.min_crossings,
                "priority": rule.priority,
            }
            if cell is None or cell["n"] < rule.min_crossings or fit is None:
                verdicts.append(dict(base,
                                     n=0 if cell is None else cell["n"],
                                     verdict=VERDICT_UNDETERMINED))
                continue
            # 按规则置信度构造区间，与 ±max_bias 比较
            alpha = 1.0 - rule.confidence
            half = float(stats.t.ppf(1.0 - alpha / 2.0, fit["dof"])
                         * fit["resid_sd"] / (cell["n"] ** 0.5))
            bias = cell["bias"]
            low, high = bias - half, bias + half
            if low > rule.max_bias or high < -rule.max_bias:
                verdict = VERDICT_EXCEEDS
            elif abs(bias) > rule.max_bias:
                verdict = VERDICT_SUSPECT
            else:
                verdict = VERDICT_CLEARED
            verdicts.append(dict(base, n=cell["n"], bias=bias,
                                 interval=[low, high], verdict=verdict))
    return verdicts


def affected_units(bundle, edition, verdicts, pair_map):
    """把越界/待证判定展开为受影响的 (exam, item) 评分单元。"""
    locked = defaultdict(list)   # (exam, item) -> [判定]
    for verdict in verdicts:
        if verdict["verdict"] not in LOCKED_VERDICTS:
            continue
        for score in bundle.scores:
            if score.kind != "first" or score.item != verdict["item"]:
                continue
            if score.rater != verdict["rater"]:
                continue
            exam = bundle.exams[score.exam]
            if exam.rubric != edition or exam.cohort != verdict["cohort"]:
                continue
            locked[(score.exam, verdict["item"])].append(verdict)
    units = []
    for (exam_id, item), related in sorted(locked.items()):
        exam = bundle.exams[exam_id]
        worst = (VERDICT_EXCEEDS if any(v["verdict"] == VERDICT_EXCEEDS for v in related)
                 else VERDICT_SUSPECT)
        units.append({
            "exam": exam_id,
            "item": item,
            "cohort": exam.cohort,
            "script": exam.script,
            "teacher": exam.teacher,
            "raters": sorted({v["rater"] for v in related}),
            "status": worst,
            "priority": min(v["priority"] for v in related),
            "max_abs_bias": max(abs(v.get("bias", 0.0)) for v in related),
            "pair_status": pair_map.get(exam_id),
        })
    return units


def releasable_units(bundle, edition, locked_units, pair_map):
    """本轮未被锁定的 (exam, item) 单元：可正常查分。"""
    locked = {(u["exam"], u["item"]) for u in locked_units}
    seen, out = set(), []
    for score in bundle.scores:
        if score.kind != "first":
            continue
        exam = bundle.exams[score.exam]
        if exam.rubric != edition:
            continue
        key = (score.exam, score.item)
        if key in locked or key in seen:
            continue
        seen.add(key)
        out.append({"exam": score.exam, "item": score.item,
                    "cohort": exam.cohort, "pair_status": pair_map.get(score.exam)})
    return out
