"""复听名额安排：资格、等级敏感度、名额分配与仲裁线索。

规则要点（见 data-contract.md）：
- 报名时的课程老师或见过旧评分的人不能为同一场提供独立结论；
- 复听员须覆盖所涉分项（eligible_items），并受名额 capacity 限制；
- 任一替代分可能改变等级时须两名独立复听且分差不大于 8，
  以复核小组授权选择的成绩为准；无法达成进入仲裁；
- 一次复听能支持哪些分项由量表共同分项决定。
"""
from collections import defaultdict

GRADE_THRESHOLD = 70.0
MAX_SCORE = 100
AGREE_TOLERANCE = 8


def eligible_reviewers(bundle, exam_id, item, exclude_raters=()):
    """能为该场该分项提供独立结论的复听员及排除原因。"""
    exam = bundle.exams[exam_id]
    eligible, rejected = [], []
    for av in bundle.availability:
        reasons = []
        if av.rater in exclude_raters:
            reasons.append("already_scored")
        if item not in av.eligible_items:
            reasons.append("item_not_eligible")
        if exam_id in av.seen_exams:
            reasons.append("seen_scores")
        if exam.teacher in av.recuse_teachers:
            reasons.append("recused_teacher")
        if reasons:
            rejected.append({"rater": av.rater, "reasons": reasons})
        else:
            eligible.append(av.rater)
    return eligible, rejected


def item_score_mean(scores):
    return sum(s.score for s in scores) / len(scores) if scores else None


def grade(items_scores, weights=None):
    """各分项有效分按权重均分判等级；任一分项缺失返回 None。"""
    if any(v is None for v in items_scores.values()):
        return None
    if weights:
        total = sum(weights[k] for k in items_scores)
        return sum(items_scores[k] * weights[k] for k in items_scores) / total
    return sum(items_scores.values()) / len(items_scores)


def grade_sensitive(current_items, item):
    """替换该分项为 0..满分 中某个值是否可能改变是否过线。

    其他分项缺失时无法判定，返回 None（调用方按敏感处理）。
    """
    others = [v for k, v in current_items.items() if k != item]
    if any(v is None for v in others) or current_items.get(item) is None:
        return None
    base = sum(others)
    n = len(current_items)
    # 当前等级
    current = (base + current_items[item]) / n >= GRADE_THRESHOLD
    # 存在某个可行替代分使等级翻转？
    for substitute in (0, MAX_SCORE):
        if ((base + substitute) / n >= GRADE_THRESHOLD) != current:
            return True
    # 端点未翻转则中间值也不会（关于替代分单调）
    return False


def valid_blind_relistens(bundle, exam_id, item, blind_map):
    """该场该分项已收到的有效盲听：复听员须具备该分项资格。"""
    valids, invalids = [], []
    for score in blind_map.get((exam_id, item), []):
        av = next((a for a in bundle.availability if a.rater == score.rater), None)
        if av is not None and item not in av.eligible_items:
            invalids.append({"rater": score.rater, "score": score.score,
                             "reason": "item_not_eligible"})
        else:
            valids.append(score)
    return valids, invalids


def review_case(bundle, exam_id, item, current_items, blind_map, scale=None,
                review_edition=None, as_of=None):
    """汇总一个待复核单元的证据状态与所需名额。"""
    exam = bundle.exams[exam_id]
    sensitive = grade_sensitive(current_items, item)
    # 敏感度未知（分项分缺失）时按敏感处理
    required = 1 if sensitive is False else 2
    valids, invalids = valid_blind_relistens(bundle, exam_id, item, blind_map)
    scores = [v.score for v in valids]
    state = "open"
    note = None
    # 量表决定这次复听能支持哪些分项：跨版无共同分项时复听不适用
    scale_supported = True
    if scale is not None and review_edition is not None:
        scale_supported = item in scale.relisten_supported_items(exam.rubric,
                                                                 review_edition)
    if not scale_supported:
        state = "arbitration"
        note = (f"分项 {item} 在 {exam.rubric} 与现行 {review_edition} 量表间"
                "无共同分项，复听结果不能支持，需同版复听或交仲裁")
    elif len(scores) >= required:
        if required >= 2 and scores and max(scores) - min(scores) > AGREE_TOLERANCE:
            state = "arbitration"
            note = f"复听分差 {max(scores) - min(scores)} 超过 {AGREE_TOLERANCE}"
        else:
            state = "evidence_complete"
    missing = max(required - len(scores), 0) if scale_supported else 0
    eligible, rejected = eligible_reviewers(
        bundle, exam_id, item,
        exclude_raters={v.rater for v in valids})
    return {
        "exam": exam_id,
        "item": item,
        "grade_sensitive": sensitive,
        "scale_supported": scale_supported,
        "required_relistens": required,
        "valid_relistens": [{"rater": v.rater, "score": v.score,
                             "received": v.received.isoformat()} for v in valids],
        "invalid_relistens": invalids,
        "missing_relistens": missing,
        "state": state,
        "note": note,
        "eligible_reviewers": eligible,
        "rejected_reviewers": rejected,
    }


def plan_assignments(bundle, cases, units):
    """按规则优先级、偏差量级与等级敏感度分配复听名额。

    返回每条安排及其用途：判清评分员差异（rater_evidence）、
    补出个人成绩的有效证据（score_substitute）或两者（both）。
    """
    order = []
    for case in cases:
        unit = next((u for u in units
                     if u["exam"] == case["exam"] and u["item"] == case["item"]), None)
        # 个案自带优先级（未结裁决为 0）优先于锁定单元清单
        priority = case.get("priority",
                            unit["priority"] if unit else 9)
        max_abs_bias = (unit["max_abs_bias"] if unit else 0.0)
        order.append((priority, -max_abs_bias,
                      case["grade_sensitive"] is False,
                      case["exam"], case))
    order.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    remaining = {av.rater: av.capacity for av in bundle.availability}
    assignments, unmet = [], []
    for _, _, _, _, case in order:
        need = case["missing_relistens"]
        if need <= 0:
            continue
        for rater in case["eligible_reviewers"]:
            if need <= 0:
                break
            if remaining.get(rater, 0) <= 0:
                continue
            remaining[rater] -= 1
            need -= 1
            purposes = []
            if case["grade_sensitive"] is not False:
                purposes.append("score_substitute")
            purposes.append("rater_evidence")
            assignments.append({
                "exam": case["exam"],
                "item": case["item"],
                "rater": rater,
                "purpose": "both" if len(purposes) > 1 else purposes[0],
            })
        if need > 0:
            unmet.append({"exam": case["exam"], "item": case["item"],
                          "missing_relistens": need})
    return assignments, unmet, remaining
