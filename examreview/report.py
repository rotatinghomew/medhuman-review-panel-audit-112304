"""把结构检查、分歧诊断、风险判定、复听安排与成绩通知串成一轮报告。"""
from . import models, notify, panel, risk, structure
from .scale import Scale


def _current_items(bundle, exam_id, effective, scale):
    """一场各分项的现行有效分（供等级敏感度判断）。"""
    exam = bundle.exams[exam_id]
    items = {}
    for item in scale.items(exam.rubric):
        entry = effective.get((exam_id, item))
        items[item] = entry["score"] if entry else None
    return items


def run_round(bundle, edition=None, as_of=None):
    """对一轮（一个量表版次）产出完整诊断与复核报告。"""
    edition = edition or bundle.latest_edition()
    scale = Scale(bundle.scale)
    pair_map = structure.exam_pair_status(bundle)
    first_map = structure.first_scores(bundle)
    blind_map = structure.blind_scores(bundle, as_of)

    # 1. 结构：配对状态、未完成抽查、交叉与连通性
    structure_info = structure.structure_report(bundle, edition)

    # 2. 诊断：三种候选办法 + 单元偏差
    diagnosis = models.diagnose_round(bundle, edition, pair_map, first_map,
                                      blind_map, as_of)

    # 3. 风险判定：单元 verdict、锁定与可查分单元
    verdicts = risk.evaluate_rules(bundle, edition, diagnosis, pair_map)
    locked_units = risk.affected_units(bundle, edition, verdicts, pair_map)
    releasable = risk.releasable_units(bundle, edition, locked_units, pair_map)

    # 4. 现行有效分与等级
    effective = notify.effective_item_scores(bundle, first_map, as_of)
    grades = notify.exam_grades(bundle, effective, scale)

    # 5. 复核个案与名额安排
    cases = []
    for unit in locked_units:
        current = _current_items(bundle, unit["exam"], effective, scale)
        case = panel.review_case(bundle, unit["exam"], unit["item"], current,
                                 blind_map, scale, edition, as_of)
        case["status"] = unit["status"]
        case["priority"] = unit["priority"]
        case["raters"] = unit["raters"]
        case["max_abs_bias"] = unit["max_abs_bias"]
        cases.append(case)
    # 未结裁决涉及的单元即使不在锁定清单也纳入个案
    open_adj = notify.open_adjudications(bundle, as_of)
    cased = {(c["exam"], c["item"]) for c in cases}
    for (exam_id, item), status in sorted(open_adj.items()):
        if (exam_id, item) in cased:
            continue
        current = _current_items(bundle, exam_id, effective, scale)
        case = panel.review_case(bundle, exam_id, item, current, blind_map,
                                 scale, edition, as_of)
        case["status"] = "adjudication_" + status
        case["priority"] = 0
        case["raters"] = []
        cases.append(case)
    assignments, unmet, remaining = panel.plan_assignments(bundle, cases, locked_units)

    # 6. 通知状态与校准留档
    states = notify.notice_states(bundle, effective, locked_units, open_adj, as_of)
    ledger = notify.calibration_ledger(bundle, as_of)

    return {
        "edition": edition,
        "as_of": as_of.isoformat() if as_of else None,
        "structure": structure_info,
        "diagnosis": diagnosis,
        "risk": {
            "verdicts": verdicts,
            "locked_units": locked_units,
            "releasable_count": len(releasable),
        },
        "review": {
            "cases": cases,
            "assignments": assignments,
            "unmet": unmet,
            "remaining_capacity": remaining,
        },
        "notify": {
            "states": {f"{k[0]}|{k[1]}": v for k, v in sorted(states.items())},
            "grades": grades,
            "effective_scores": {f"{k[0]}|{k[1]}": v
                                 for k, v in sorted(effective.items())},
        },
        "calibration": ledger,
        "scale": {
            "editions": scale.editions(),
            "relisten_supported": {
                ed: scale.relisten_supported_items(ed, edition)
                for ed in scale.editions()
            },
        },
    }
