"""成绩通知与校准留档。

- 现行成绩以获得授权的判决为准（confirmed 的 authorized_score）；
- 无争议分项按期通知；被锁分项与未结裁决保持暂扣；
- 未结的个案不因整体异常消失而写成已确认；
- 只有已确定的判决回到校准历史，未确认成绩不进校准数据。
"""
from collections import defaultdict

STATE_PUBLISHED = "published"
STATE_READY = "ready_to_publish"      # 已有授权分，可发布
STATE_RELEASABLE = "releasable"       # 无争议，可按期通知
STATE_HELD_RISK = "held_risk"         # 批次风险锁定
STATE_HELD_ADJUDICATION = "held_adjudication"  # 裁决未结
STATE_PROPOSED_PENDING = "proposed_pending"    # 已提议待授权


def authorized_scores(bundle, as_of=None):
    """已确认裁决给出的授权分：(exam, item) -> 分数。"""
    out = {}
    for adj in bundle.adjudications:
        if adj.status != "confirmed" or adj.authorized_score is None:
            continue
        if as_of is not None and adj.received and adj.received > as_of:
            continue
        out[(adj.exam, adj.item)] = adj.authorized_score
    return out


def open_adjudications(bundle, as_of=None):
    """截至 as_of 仍未确认的裁决事项：(exam, item) -> 最新状态。"""
    latest = {}
    for adj in sorted(bundle.adjudications,
                      key=lambda a: (a.received is not None, a.received or a.ordered_on)):
        if as_of is not None:
            marker = adj.received or adj.ordered_on
            if marker and marker > as_of:
                continue
        if adj.status == "confirmed":
            latest.pop((adj.exam, adj.item), None)
        else:
            latest[(adj.exam, adj.item)] = adj.status
    return latest


def effective_item_scores(bundle, first_map, as_of=None):
    """每个 (exam, item) 的现行有效分与来源。"""
    authorized = authorized_scores(bundle, as_of)
    effective = {}
    for key, scores in first_map.items():
        if key in authorized:
            effective[key] = {"score": float(authorized[key]), "source": "authorized"}
        else:
            mean = sum(s.score for s in scores) / len(scores)
            effective[key] = {"score": mean, "source": "original"}
    # 授权分可能对应没有初评分的键（防御性处理）
    for key, value in authorized.items():
        effective.setdefault(key, {"score": float(value), "source": "authorized"})
    return effective


def exam_grades(bundle, effective, scale):
    """按场次汇总均分与等级（各分项均有有效分时）。"""
    by_exam = defaultdict(dict)
    for (exam_id, item), entry in effective.items():
        by_exam[exam_id][item] = entry["score"]
    grades = {}
    for exam_id, items in by_exam.items():
        exam = bundle.exams[exam_id]
        expected = scale.items(exam.rubric)
        if any(items.get(it) is None for it in expected):
            grades[exam_id] = {"mean": None, "level": None}
            continue
        weights = {it: (scale.weight(exam.rubric, it) or 1.0) for it in expected}
        total = sum(weights.values())
        mean = sum(items[it] * weights[it] for it in expected) / total
        grades[exam_id] = {"mean": mean, "level": "pass" if mean >= 70 else "fail"}
    return grades


def notice_states(bundle, effective, locked_units, open_adj, as_of=None):
    """每个有初评分或通知记录的 (exam, item) 的通知状态。"""
    locked = {(u["exam"], u["item"]) for u in locked_units}
    notices = {}
    for notice in bundle.notices:
        if as_of is not None and notice.date and notice.date > as_of:
            continue
        notices[(notice.exam, notice.item)] = notice.notice_state
    keys = set(effective) | set(notices)
    states = {}
    for key in sorted(keys):
        exam_id, item = key
        notice = notices.get(key)
        if key in open_adj:
            states[key] = {"state": STATE_HELD_ADJUDICATION,
                           "detail": open_adj[key]}
        elif notice == STATE_PUBLISHED:
            states[key] = {"state": STATE_PUBLISHED, "detail": None}
        elif key in locked:
            states[key] = {"state": STATE_HELD_RISK, "detail": None}
        elif notice == "held":
            states[key] = {"state": STATE_HELD_RISK, "detail": "notice_held"}
        elif notice == "proposed":
            entry = effective.get(key)
            if entry and entry["source"] == "authorized":
                states[key] = {"state": STATE_READY, "detail": "authorized"}
            else:
                states[key] = {"state": STATE_PROPOSED_PENDING, "detail": None}
        else:
            states[key] = {"state": STATE_RELEASABLE, "detail": None}
    return states


def calibration_ledger(bundle, as_of=None):
    """评分员校准留档：只收已确定的判决。

    同一 (exam, item) 只保留最新状态；未确认的成绩
    （open / sent_to_arbitration / 仅提议的通知）不进入校准数据。
    """
    latest = {}
    for adj in sorted(bundle.adjudications,
                      key=lambda a: (a.received is not None,
                                     a.received or a.ordered_on)):
        if as_of is not None:
            marker = adj.received or adj.ordered_on
            if marker and marker > as_of:
                continue
        latest[(adj.exam, adj.item)] = adj
    confirmed, excluded = [], []
    for (exam_id, item), adj in sorted(latest.items()):
        entry = {"exam": exam_id, "item": item, "status": adj.status,
                 "authorized_score": adj.authorized_score}
        if adj.status == "confirmed" and adj.authorized_score is not None:
            confirmed.append(entry)
        else:
            excluded.append(entry)
    return {"final": confirmed, "withheld": excluded}
