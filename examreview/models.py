"""分歧检验的候选办法与可估计性分析。

三种互相印证的办法：
A. 双向固定效应：初评分 ~ 评分员 + 剧本，只用独立成对场次；
B. 场内配对差分：同一独立场次内两名评分员之差，剧本效应自然消去；
C. 独立盲听锚点：初评分与完成抽查的盲听分之差，按实际抽中概率
   做 Horvitz-Thompson 加权（prob=1 的必查只作个案证据，不外推）。
"""
from collections import defaultdict

import numpy as np
from scipy import stats

from .structure import PAIR_INDEPENDENT, completed_samples


def _round_first_rows(bundle, edition, item, pair_map):
    """本轮某分项可用于估计的初评分行（独立成对场次）。"""
    rows = []
    for score in bundle.scores:
        if score.kind != "first" or score.item != item:
            continue
        exam = bundle.exams[score.exam]
        if exam.rubric != edition:
            continue
        if pair_map.get(score.exam) != PAIR_INDEPENDENT:
            continue
        rows.append((score.rater, exam.script, exam.cohort, score.score, score.exam))
    return rows


def fit_two_way(rows):
    """拟合 分数 ~ 评分员 + 剧本（和为零约束），返回效应与残差信息。"""
    raters = sorted({r for r, _, _, _, _ in rows})
    scripts = sorted({s for _, s, _, _, _ in rows})
    n_r, n_s = len(raters), len(scripts)
    p = 1 + n_r + n_s
    design = np.zeros((len(rows) + 2, p))
    y = np.zeros(len(rows) + 2)
    for i, (rater, script, _, value, _) in enumerate(rows):
        design[i, 0] = 1.0
        design[i, 1 + raters.index(rater)] = 1.0
        design[i, 1 + n_r + scripts.index(script)] = 1.0
        y[i] = value
    design[len(rows), 1:1 + n_r] = 1.0      # 评分员效应和为零
    design[len(rows) + 1, 1 + n_r:] = 1.0   # 剧本效应和为零
    beta, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design[:len(rows)] @ beta
    resid = y[:len(rows)] - fitted
    rank = int(np.linalg.matrix_rank(design[:len(rows)]))
    dof = max(len(rows) - rank, 1)
    sd = float(np.sqrt(resid @ resid / dof))
    return {
        "grand_mean": float(beta[0]),
        "rater_effects": dict(zip(raters, beta[1:1 + n_r].tolist())),
        "script_effects": dict(zip(scripts, beta[1 + n_r:].tolist())),
        "resid_sd": sd,
        "dof": dof,
        "rank": rank,
        "n_params": p,
        # 两个和为零约束后满秩即可估计
        "estimable": rank == p - 2,
        "n": len(rows),
    }


def method_paired_diffs(bundle, edition, item, pair_map, first_map):
    """办法 B：场内配对差分估计评分员差异（剧本效应自动消去）。"""
    diffs = []
    for (exam_id, it), scores in first_map.items():
        if it != item:
            continue
        exam = bundle.exams[exam_id]
        if exam.rubric != edition or pair_map.get(exam_id) != PAIR_INDEPENDENT:
            continue
        if len(scores) != 2:
            continue
        a, b = sorted(scores, key=lambda s: s.rater)
        diffs.append((a.rater, b.rater, a.score - b.score))
    if not diffs:
        return {"n": 0, "rater_effects": {}, "resid_sd": None}
    raters = sorted({r for pair in diffs for r in pair[:2]})
    design = np.zeros((len(diffs) + 1, len(raters)))
    y = np.zeros(len(diffs) + 1)
    for i, (ra, rb, diff) in enumerate(diffs):
        design[i, raters.index(ra)] = 1.0
        design[i, raters.index(rb)] = -1.0
        y[i] = diff
    design[len(diffs), :] = 1.0  # 效应和为零
    beta, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    resid = y[:len(diffs)] - design[:len(diffs)] @ beta
    dof = max(len(diffs) - int(np.linalg.matrix_rank(design[:len(diffs)])), 1)
    return {
        "n": len(diffs),
        "rater_effects": dict(zip(raters, beta.tolist())),
        "resid_sd": float(np.sqrt(resid @ resid / dof)),
    }


def method_blind_anchor(bundle, edition, item, pair_map, first_map, blind_map,
                        as_of=None):
    """办法 C：独立盲听锚点。

    概率抽查（prob<1）按 1/prob 加权外推到本轮；必查（prob=1）
    与无抽查登记的盲听只作个案证据单列。sent 状态不计入。
    """
    sample_by_exam = {s.exam: s for s in completed_samples(bundle.samples, as_of)}
    weighted = defaultdict(list)   # rater -> [(weight, diff)]
    mandatory = defaultdict(list)  # rater -> [diff]
    for (exam_id, it), blinds in blind_map.items():
        if it != item:
            continue
        exam = bundle.exams[exam_id]
        if exam.rubric != edition:
            continue
        firsts = first_map.get((exam_id, it), [])
        if not firsts:
            continue
        blind_mean = float(np.mean([b.score for b in blinds]))
        sample = sample_by_exam.get(exam_id)
        for score in firsts:
            diff = score.score - blind_mean
            if sample is not None and sample.prob is not None and sample.prob < 1:
                weighted[score.rater].append((1.0 / sample.prob, diff))
            else:
                mandatory[score.rater].append(diff)
    def _summarize(entries):
        out = {}
        for rater, pairs in sorted(entries.items()):
            weights = np.array([w for w, _ in pairs])
            diffs = np.array([d for _, d in pairs])
            out[rater] = {
                "n": len(pairs),
                "weighted_mean": float((weights * diffs).sum() / weights.sum()),
            }
        return out
    return {
        "probability_sample": _summarize(weighted),
        "mandatory_or_unregistered": {r: {"n": len(v), "mean": float(np.mean(v))}
                                      for r, v in sorted(mandatory.items())},
    }


def cell_biases(bundle, edition, item, pair_map, fit):
    """评分员×年级单元的剧本调整偏差及区间。

    偏差 = 该单元各独立场次 初评分 - 总平均 - 剧本效应 的均值；
    区间用本轮残差标准差。交叉数不足的单元由调用方按规则处理。
    """
    script_effects = fit["script_effects"]
    grand = fit["grand_mean"]
    cells = defaultdict(list)
    for rater, script, cohort, value, _ in _round_first_rows(bundle, edition, item, pair_map):
        cells[(rater, cohort)].append(value - grand - script_effects[script])
    result = {}
    for (rater, cohort), values in sorted(cells.items()):
        n = len(values)
        mean = float(np.mean(values))
        half = float(stats.t.ppf(0.975, fit["dof"]) * fit["resid_sd"] / np.sqrt(n))
        result[(rater, cohort)] = {"n": n, "bias": mean, "half_width": half}
    return result


def diagnose_round(bundle, edition, pair_map, first_map, blind_map, as_of=None):
    """本轮全部分项的诊断：三种办法、可估计性与单元偏差。"""
    report = {}
    for item in sorted({s.item for s in bundle.scores}):
        rows = _round_first_rows(bundle, edition, item, pair_map)
        if not rows:
            continue
        fit = fit_two_way(rows)
        cells = cell_biases(bundle, edition, item, pair_map, fit)
        report[item] = {
            "two_way": {
                "n": fit["n"],
                "estimable": fit["estimable"],
                "resid_sd": fit["resid_sd"],
                "dof": fit["dof"],
                "grand_mean": fit["grand_mean"],
                "rater_effects": fit["rater_effects"],
                "script_effects": fit["script_effects"],
            },
            "paired_diffs": method_paired_diffs(bundle, edition, item, pair_map, first_map),
            "blind_anchor": method_blind_anchor(bundle, edition, item, pair_map,
                                                first_map, blind_map, as_of),
            "cells": {f"{rater}|{cohort}": dict(v, rater=rater, cohort=cohort)
                      for (rater, cohort), v in cells.items()},
        }
    return report
