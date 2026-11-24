"""交叉结构与记录完整性检查。

区分三种不能当作独立复核的记录：
- 角色登记重复（同一位评分员在同一场出现两次）；
- 配对评分签阅同一份记录（process=paired 且 note 相同）；
- 抽中复听但尚未完成（review_sample.stage=sent）。
"""
from collections import defaultdict

PAIR_INDEPENDENT = "independent"
PAIR_SHARED_NOTE = "paired_shared_note"
PAIR_DUPLICATED = "rater_duplicated"


def roles_by_exam(roles):
    grouped = defaultdict(list)
    for role in roles:
        grouped[role.exam].append(role)
    return grouped


def pair_status(roles_for_exam):
    """一场的两人评分是否构成两份独立意见。"""
    raters = [r.rater for r in roles_for_exam]
    if len(set(raters)) != len(raters):
        return PAIR_DUPLICATED
    if any(r.process == "paired" for r in roles_for_exam):
        notes = {r.note for r in roles_for_exam}
        if len(notes) == 1:
            return PAIR_SHARED_NOTE
    return PAIR_INDEPENDENT


def exam_pair_status(bundle):
    """全部场次的配对状态：exam -> 状态。"""
    return {exam: pair_status(rs) for exam, rs in roles_by_exam(bundle.roles).items()}


def completed_samples(samples, as_of=None):
    """已完成的复听抽查；stage=sent 表示已抽中未确认完成，不计入。"""
    return [s for s in samples if s.stage == "completed"
            and (as_of is None or (s.received and s.received <= as_of))]


def pending_samples(samples, as_of=None):
    """已抽中但未完成的抽查，不能当成已有独立复核。"""
    return [s for s in samples if s.stage != "completed"
            and (as_of is None or (s.received and s.received <= as_of))]


def blind_scores(bundle, as_of=None):
    """按 (exam, item) 归组的盲听复听分。"""
    grouped = defaultdict(list)
    for score in bundle.scores:
        if score.kind != "blind":
            continue
        if as_of is not None and score.received and score.received > as_of:
            continue
        grouped[(score.exam, score.item)].append(score)
    return grouped


def ineligible_blind_records(bundle, as_of=None):
    """复听员资格与所评分项不符的盲听记录（不能计入复核证据）。"""
    flagged = []
    for score in bundle.scores:
        if score.kind != "blind":
            continue
        if as_of is not None and score.received and score.received > as_of:
            continue
        av = next((a for a in bundle.availability if a.rater == score.rater), None)
        if av is not None and score.item not in av.eligible_items:
            flagged.append({"exam": score.exam, "item": score.item,
                            "rater": score.rater, "reason": "item_not_eligible"})
    return flagged


def first_scores(bundle, exam_ids=None):
    """按 (exam, item) 归组的初评分。"""
    grouped = defaultdict(list)
    for score in bundle.scores:
        if score.kind != "first":
            continue
        if exam_ids is not None and score.exam not in exam_ids:
            continue
        grouped[(score.exam, score.item)].append(score)
    return grouped


def crossing_tables(bundle, edition, item, pair_map):
    """本轮内评分员×剧本、评分员×年级的交叉计数（仅独立成对场次）。"""
    rater_script = defaultdict(int)
    rater_cohort = defaultdict(int)
    for score in bundle.scores:
        if score.kind != "first" or score.item != item:
            continue
        exam = bundle.exams[score.exam]
        if exam.rubric != edition:
            continue
        if pair_map.get(score.exam) != PAIR_INDEPENDENT:
            continue
        rater_script[(score.rater, exam.script)] += 1
        rater_cohort[(score.rater, exam.cohort)] += 1
    return rater_script, rater_cohort


def connectivity(bundle, edition, item, pair_map):
    """评分员—剧本二部图的连通分量与空缺交叉格。

    空缺的 (评分员, 剧本) 格意味着该评分员在该剧本上的表现
    缺少交叉，相关交互差异只能保留疑问。
    """
    rater_script, _ = crossing_tables(bundle, edition, item, pair_map)
    raters = sorted({r for r, _ in rater_script})
    scripts = sorted({s for _, s in rater_script})
    neighbors = defaultdict(set)
    for rater, script in rater_script:
        neighbors[("r", rater)].add(("s", script))
        neighbors[("s", script)].add(("r", rater))
    seen = set()
    components = []
    for start in neighbors:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.add(node)
            stack.extend(neighbors[node] - seen)
        components.append(sorted(comp))
    missing = [(r, s) for r in raters for s in scripts
               if (r, s) not in rater_script]
    return {
        "connected": len(components) <= 1,
        "components": components,
        "missing_crossings": missing,
    }


def structure_report(bundle, edition):
    """结构诊断汇总：配对状态、抽查状态、交叉与连通性。"""
    pair_map = exam_pair_status(bundle)
    exams_in_round = [e.id for e in bundle.exams.values() if e.rubric == edition]
    pairs = defaultdict(list)
    for exam in exams_in_round:
        pairs[pair_map.get(exam, PAIR_INDEPENDENT)].append(exam)
    items = sorted({s.item for s in bundle.scores})
    crossings = {}
    for item in items:
        info = connectivity(bundle, edition, item, pair_map)
        crossings[item] = {
            "connected": info["connected"],
            "missing_crossings": [
                {"rater": r, "script": s} for r, s in info["missing_crossings"]
            ],
        }
    return {
        "edition": edition,
        "exams_in_round": len(exams_in_round),
        "pair_status": {k: sorted(v) for k, v in sorted(pairs.items())},
        "pending_samples": [
            {"id": s.id, "exam": s.exam, "stratum": s.stratum, "prob": s.prob}
            for s in pending_samples(bundle.samples)
        ],
        "ineligible_blind_records": ineligible_blind_records(bundle),
        "crossings": crossings,
    }
