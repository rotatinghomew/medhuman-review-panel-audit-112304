"""模拟会谈评分诊断与成绩复核的命令行入口。

用法：
    python3 review_tool.py data structure            # 交叉结构与记录完整性
    python3 review_tool.py data diagnose             # 分歧检验（三种候选办法）
    python3 review_tool.py data risk                 # 批次风险判定与单元划分
    python3 review_tool.py data plan                 # 复听名额安排与仲裁线索
    python3 review_tool.py data notify               # 成绩通知状态与校准留档
    python3 review_tool.py data report --format json # 全部结果的 JSON

常用选项：--round R2 选择轮次（默认最新量表版次），
--as-of YYYY-MM-DD 只采用该日期前收到的证据（复听、裁决、通知）。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from examreview.bundle import Bundle
from examreview.report import run_round

VERDICT_LABEL = {
    "exceeds": "确认越界（可疑，锁定）",
    "suspect": "待证（点估计越界，先锁定）",
    "cleared": "可查分",
    "undetermined_lack_of_crossings": "交叉不足（保留疑问）",
}

STATE_LABEL = {
    "published": "已发布",
    "ready_to_publish": "可发布（授权分）",
    "releasable": "可按期通知",
    "held_risk": "暂扣（批次风险）",
    "held_adjudication": "暂扣（裁决未结）",
    "proposed_pending": "已提议待授权",
}

PURPOSE_LABEL = {
    "rater_evidence": "判清评分员差异",
    "score_substitute": "补出个人成绩",
    "both": "两者都需要",
}


def _fmt_signed(value, digits=2):
    return f"{value:+.{digits}f}"


def show_structure(result, out):
    info = result["structure"]
    print(f"轮次（量表版次）：{info['edition']}，场次 {info['exams_in_round']}", file=out)
    labels = {
        "independent": "两份独立意见",
        "paired_shared_note": "配对共用记录（只算一份意见）",
        "rater_duplicated": "角色登记重复（不算独立复核）",
    }
    for key, exams in info["pair_status"].items():
        print(f"  {labels.get(key, key)}：{len(exams)} 场 "
              f"{'、'.join(exams)}", file=out)
    pending = info["pending_samples"]
    print(f"  已抽中未完成复听：{len(pending)} 场（不计入独立复核）", file=out)
    for row in pending:
        print(f"    {row['id']} {row['exam']} 层={row['stratum']} 抽中概率={row['prob']}",
              file=out)
    bad = info.get("ineligible_blind_records", [])
    print(f"  复听员资格与分项不符的盲听记录：{len(bad)} 条（不计入证据）", file=out)
    for row in bad:
        print(f"    {row['exam']}/{row['item']} 复听员 {row['rater']}（{row['reason']}）",
              file=out)
    for item, cross in info["crossings"].items():
        state = "连通" if cross["connected"] else "不连通"
        missing = cross["missing_crossings"]
        print(f"  分项 {item}：评分员×剧本图{state}；"
              f"空缺交叉 {len(missing)} 格（相关交互只能保留疑问）", file=out)
        if missing:
            by_rater = {}
            for cell in missing:
                by_rater.setdefault(cell["rater"], []).append(cell["script"])
            for rater, scripts in sorted(by_rater.items()):
                print(f"    {rater} 未覆盖 {'、'.join(scripts)}", file=out)


def show_diagnose(result, out):
    diag = result["diagnosis"]
    for item, block in sorted(diag.items()):
        two = block["two_way"]
        print(f"分项 {item}：独立初评 n={two['n']}，残差 sd={two['resid_sd']:.2f}，"
              f"设计{'可估计' if two['estimable'] else '不可完全估计'}", file=out)
        raters = " ".join(f"{r}{_fmt_signed(v, 1)}" for r, v
                          in sorted(two["rater_effects"].items()))
        scripts = " ".join(f"{s}{_fmt_signed(v, 1)}" for s, v
                           in sorted(two["script_effects"].items()))
        print(f"  办法A 双向效应：评分员[{raters}]", file=out)
        print(f"                剧本  [{scripts}]", file=out)
        paired = block["paired_diffs"]
        if paired["rater_effects"]:
            effects = " ".join(f"{r}{_fmt_signed(v, 1)}" for r, v
                               in sorted(paired["rater_effects"].items()))
            print(f"  办法B 场内差分（n={paired['n']}）：[{effects}]", file=out)
        anchor = block["blind_anchor"]
        prob = anchor["probability_sample"]
        if prob:
            text = " ".join(f"{r}{_fmt_signed(v['weighted_mean'], 1)}(n={v['n']})"
                            for r, v in prob.items())
            print(f"  办法C 盲听锚点（概率抽查加权）：[{text}]", file=out)
        mand = anchor["mandatory_or_unregistered"]
        if mand:
            text = " ".join(f"{r}{_fmt_signed(v['mean'], 1)}(n={v['n']})"
                            for r, v in mand.items())
            print(f"  办法C 必查/个案（不外推）：[{text}]", file=out)


def show_risk(result, out):
    verdicts = result["risk"]["verdicts"]
    print("批次风险判定（按规则置信度区间与 ±max_bias 比较）：", file=out)
    for v in verdicts:
        label = VERDICT_LABEL[v["verdict"]]
        if "interval" in v:
            detail = (f"偏差{_fmt_signed(v['bias'])} "
                      f"区间[{_fmt_signed(v['interval'][0])},{_fmt_signed(v['interval'][1])}] "
                      f"界限±{v['max_bias']}")
        else:
            detail = f"n={v['n']} 不足 min_crossings={v['min_crossings']}"
        print(f"  {v['cohort']}/{v['item']} {v['rater']}：{label}（{detail}）", file=out)
    locked = result["risk"]["locked_units"]
    print(f"锁定评分单元 {len(locked)} 个；可正常查分单元 "
          f"{result['risk']['releasable_count']} 个", file=out)
    for u in locked:
        print(f"  {u['exam']}/{u['item']}（{u['cohort']}，评分员 "
              f"{'、'.join(u['raters'])}，优先级 {u['priority']}）", file=out)


def show_plan(result, out):
    review = result["review"]
    print("复核个案与复听名额：", file=out)
    for case in review["cases"]:
        sensitive = case["grade_sensitive"]
        sensitive_text = "未知" if sensitive is None else ("是" if sensitive else "否")
        print(f"  {case['exam']}/{case['item']}：等级敏感="
              f"{sensitive_text}，"
              f"需独立复听 {case['required_relistens']} 份，"
              f"有效已收 {len(case['valid_relistens'])} 份，"
              f"仍差 {case['missing_relistens']} 份；状态 {case['state']}", file=out)
        for b in case["valid_relistens"]:
            print(f"    有效盲听 {b['rater']}={b['score']}（{b['received']}）", file=out)
        for b in case["invalid_relistens"]:
            print(f"    无效盲听 {b['rater']}={b['score']}（{b['reason']}）", file=out)
        if case["note"]:
            print(f"    说明：{case['note']}", file=out)
        if case["eligible_reviewers"]:
            print(f"    可派复听员：{'、'.join(case['eligible_reviewers'])}", file=out)
        for rej in case["rejected_reviewers"]:
            print(f"    排除 {rej['rater']}：{'、'.join(rej['reasons'])}", file=out)
    if review["assignments"]:
        print("建议安排（用途供负责人比较）：", file=out)
        for a in review["assignments"]:
            print(f"  {a['exam']}/{a['item']} → {a['rater']}："
                  f"{PURPOSE_LABEL[a['purpose']]}", file=out)
    if review["unmet"]:
        print("名额不足、仍差的独立证据：", file=out)
        for u in review["unmet"]:
            print(f"  {u['exam']}/{u['item']} 仍差 {u['missing_relistens']} 份", file=out)
    print(f"剩余名额：{review['remaining_capacity']}", file=out)


def show_notify(result, out):
    states = result["notify"]["states"]
    grouped = {}
    for key, entry in states.items():
        grouped.setdefault(entry["state"], []).append(key)
    print("成绩通知状态：", file=out)
    for state, keys in sorted(grouped.items()):
        print(f"  {STATE_LABEL.get(state, state)}：{len(keys)} 项", file=out)
        if state in ("releasable", "published"):
            # 无争议分项照常通知，不一一列举
            exams = sorted({k.split("|")[0] for k in keys})
            print(f"    涉及 {len(exams)} 场（{exams[0]}…{exams[-1]}，"
                  "明细见 JSON 报告）", file=out)
        else:
            print(f"    {'、'.join(keys)}", file=out)
    grades = result["notify"]["grades"]
    waiting = [g for g, v in sorted(grades.items()) if v["mean"] is not None]
    print(f"已可算等级的场次 {len(waiting)} 个（阈值 70）", file=out)
    ledger = result["calibration"]
    print("校准留档（仅已确定判决计入）：", file=out)
    for entry in ledger["final"]:
        print(f"  计入 {entry['exam']}/{entry['item']} 授权分 "
              f"{entry['authorized_score']}", file=out)
    for entry in ledger["withheld"]:
        print(f"  暂缓 {entry['exam']}/{entry['item']}（{entry['status']}）", file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", type=Path, help="考务交换包目录")
    parser.add_argument("command", choices=["structure", "diagnose", "risk",
                                            "plan", "notify", "report"])
    parser.add_argument("--round", dest="edition", default=None,
                        help="量表版次（默认最新一轮）")
    parser.add_argument("--as-of", dest="as_of", default=None,
                        help="只采用该日期前收到的证据，YYYY-MM-DD")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    try:
        bundle = Bundle(args.bundle)
        result = run_round(bundle, edition=args.edition, as_of=as_of)
    except (OSError, ValueError, KeyError) as error:
        print(f"资料读取失败：{error}", file=sys.stderr)
        return 2

    if args.format == "json" or args.command == "report":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    sections = {"structure": show_structure, "diagnose": show_diagnose,
                "risk": show_risk, "plan": show_plan, "notify": show_notify}
    sections[args.command](result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
