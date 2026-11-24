"""诊断与复核工具的单元测试：结构、量表、风险、名额、通知与校准。"""
import unittest
from datetime import date
from pathlib import Path

from examreview.bundle import Bundle
from examreview.scale import Scale
from examreview import models, notify, panel, risk, structure
from examreview.report import run_round

DATA = Path(__file__).resolve().parents[1] / "data"


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = Bundle(DATA)
        cls.scale = Scale(cls.bundle.scale)
        cls.pair_map = structure.exam_pair_status(cls.bundle)
        cls.result = run_round(cls.bundle)


class BundleTest(Fixture):
    def test_tables_loaded(self):
        self.assertEqual(len(self.bundle.exams), 96)
        self.assertEqual(len(self.bundle.risk_rules), 5)
        self.assertEqual(self.bundle.latest_edition(), "R2")

    def test_exam_fields(self):
        exam = self.bundle.exams["F071"]
        self.assertEqual((exam.cohort, exam.script, exam.teacher, exam.rubric),
                         ("Y3", "SC5", "T3", "R2"))


class ScaleTest(Fixture):
    def test_same_edition_all_items_supported(self):
        self.assertEqual(self.scale.relisten_supported_items("R2", "R2"),
                         ["listen", "explain", "respond"])

    def test_cross_edition_only_common_items(self):
        # 量表决定一次复听能支持哪两个分项：listen 与 explain 有共同分项
        self.assertEqual(self.scale.relisten_supported_items("R1", "R2"),
                         ["listen", "explain"])
        self.assertEqual(self.scale.relisten_supported_items("R2", "R1"),
                         ["listen", "explain"])


class StructureTest(Fixture):
    def test_pair_status(self):
        # 配对共用记录只算一份意见
        self.assertEqual(self.pair_map["F000"], structure.PAIR_SHARED_NOTE)
        # 角色登记重复不算独立复核
        self.assertEqual(self.pair_map["F019"], structure.PAIR_DUPLICATED)
        self.assertEqual(self.pair_map["F059"], structure.PAIR_DUPLICATED)
        self.assertEqual(self.pair_map["F071"], structure.PAIR_INDEPENDENT)

    def test_pending_samples_not_counted(self):
        pending = {s.exam for s in structure.pending_samples(self.bundle.samples)}
        self.assertEqual(pending, {"F000", "F036", "F072"})
        completed = {s.exam for s in structure.completed_samples(self.bundle.samples)}
        self.assertFalse(pending & completed)

    def test_ineligible_blind_record_flagged(self):
        flagged = structure.ineligible_blind_records(self.bundle)
        self.assertEqual(len(flagged), 1)
        self.assertEqual((flagged[0]["exam"], flagged[0]["item"],
                          flagged[0]["rater"]), ("F078", "explain", "K2"))

    def test_missing_crossings_reported(self):
        info = structure.connectivity(self.bundle, "R2", "explain", self.pair_map)
        self.assertTrue(info["connected"])
        self.assertIn(("J0", "SC1"), info["missing_crossings"])


class ModelTest(Fixture):
    def test_two_way_recovers_script_and_rater_effects(self):
        diag = self.result["diagnosis"]["explain"]["two_way"]
        self.assertTrue(diag["estimable"])
        # 剧本 SC2 最易说明；J3 的说明主效应最高
        self.assertEqual(max(diag["script_effects"],
                             key=diag["script_effects"].get), "SC2")
        self.assertEqual(max(diag["rater_effects"],
                             key=diag["rater_effects"].get), "J3")

    def test_paired_diffs_agree_on_j3(self):
        effects = self.result["diagnosis"]["explain"]["paired_diffs"]["rater_effects"]
        self.assertGreater(effects["J3"], 0)

    def test_blind_anchor_uses_only_completed_probability_samples(self):
        anchor = self.result["diagnosis"]["explain"]["blind_anchor"]
        # 概率抽查加权估计里不含 F071/F078 的必查个案
        self.assertIn("J0", anchor["probability_sample"])
        self.assertIn("J3", anchor["mandatory_or_unregistered"])


class RiskTest(Fixture):
    def _verdict(self, cohort, item, rater):
        for v in self.result["risk"]["verdicts"]:
            if (v["cohort"], v["item"], v["rater"]) == (cohort, item, rater):
                return v
        self.fail(f"缺少判定 {cohort}/{item}/{rater}")

    def test_flagged_cell_is_suspect_not_confirmed(self):
        v = self._verdict("Y2", "explain", "J3")
        self.assertEqual(v["verdict"], "suspect")
        self.assertGreater(v["bias"], v["max_bias"])
        # 区间跨界：不能凭异常榜定论
        self.assertLess(v["interval"][0], v["max_bias"])

    def test_same_rater_other_cells_not_held(self):
        # 不能把一位老师的所有评分一并判无效
        self.assertEqual(self._verdict("Y1", "explain", "J3")["verdict"], "cleared")
        self.assertEqual(self._verdict("Y3", "explain", "J3")["verdict"], "cleared")

    def test_insufficient_crossings_kept_open(self):
        v = self._verdict("Y2", "explain", "J4")
        self.assertEqual(v["verdict"], "undetermined_lack_of_crossings")

    def test_locked_units_scoped_to_flagged_cells(self):
        units = self.result["risk"]["locked_units"]
        locked = {(u["exam"], u["item"]) for u in units}
        for key in [("F059", "explain"), ("F063", "explain"), ("F083", "explain"),
                    ("F084", "explain"), ("F087", "explain")]:
            self.assertIn(key, locked)
        # J3 只在说明分项被标记；含 J3 的锁定单元不涉及倾听或回应
        j3_units = [u for u in units if "J3" in u["raters"]]
        self.assertTrue(j3_units)
        self.assertTrue(all(u["item"] == "explain" for u in j3_units))
        # F083 的回应被锁是因为 J7 的 Y2 回应单元，而非 J3
        f083_respond = next(u for u in units
                            if (u["exam"], u["item"]) == ("F083", "respond"))
        self.assertEqual(f083_respond["raters"], ["J7"])
        # F071 的说明由裁决流程暂扣，不在批次风险锁定内
        self.assertNotIn(("F071", "explain"), locked)


class PanelTest(Fixture):
    def test_eligibility_rules(self):
        bundle = self.bundle
        eligible, rejected = panel.eligible_reviewers(bundle, "F071", "explain")
        reasons = {r["rater"]: r["reasons"] for r in rejected}
        # 见过旧评分的人不能为同一场提供独立结论
        self.assertIn("seen_scores", reasons["K1"])
        # 报名时的课程老师相关回避
        self.assertIn("recused_teacher", reasons["K2"])
        self.assertIn("K5", eligible)

    def test_recused_teacher_for_t1_exams(self):
        _, rejected = panel.eligible_reviewers(self.bundle, "F063", "explain")
        reasons = {r["rater"]: r["reasons"] for r in rejected}
        self.assertIn("recused_teacher", reasons["K3"])

    def test_grade_sensitivity(self):
        # F071：替代分 81 使均分达到 70，等级敏感
        items = {"listen": 65.5, "explain": 66.0, "respond": 63.5}
        self.assertTrue(panel.grade_sensitive(items, "explain"))
        # 深度未过线：任何替代分都翻不了等级，不敏感
        items = {"listen": 40.0, "explain": 50.0, "respond": 40.0}
        self.assertFalse(panel.grade_sensitive(items, "explain"))
        # 分项缺失时未知
        self.assertIsNone(panel.grade_sensitive(
            {"listen": None, "explain": 66.0, "respond": 63.5}, "explain"))

    def _case(self, exam, item):
        for case in self.result["review"]["cases"]:
            if (case["exam"], case["item"]) == (exam, item):
                return case
        self.fail(f"缺少个案 {exam}/{item}")

    def test_f071_two_relistens_disagree_goes_arbitration(self):
        case = self._case("F071", "explain")
        self.assertEqual(case["state"], "arbitration")
        self.assertEqual(len(case["valid_relistens"]), 2)
        self.assertIn("18", case["note"])

    def test_f084_counts_existing_blind(self):
        case = self._case("F084", "explain")
        self.assertEqual(len(case["valid_relistens"]), 1)
        self.assertEqual(case["missing_relistens"], 1)

    def test_assignments_respect_capacity_and_purpose(self):
        review = self.result["review"]
        counts = {}
        for a in review["assignments"]:
            counts[a["rater"]] = counts.get(a["rater"], 0) + 1
            self.assertEqual(a["purpose"], "both")
        capacity = {av.rater: av.capacity for av in self.bundle.availability}
        for rater, used in counts.items():
            self.assertLessEqual(used, capacity[rater])
        # 名额有限，仍差的独立证据必须明示
        self.assertTrue(review["unmet"])


class NotifyTest(Fixture):
    def test_authorized_score_governs_current_score(self):
        effective = self.result["notify"]["effective_scores"]
        self.assertEqual(effective["F078|respond"]["score"], 72.0)
        self.assertEqual(effective["F078|respond"]["source"], "authorized")

    def test_notice_states(self):
        states = self.result["notify"]["states"]
        self.assertEqual(states["F071|explain"]["state"], "held_adjudication")
        self.assertEqual(states["F071|listen"]["state"], "published")
        # 复核中原来无争议的分项仍可按期通知
        self.assertEqual(states["F071|respond"]["state"], "releasable")
        self.assertEqual(states["F078|respond"]["state"], "ready_to_publish")
        self.assertEqual(states["F063|explain"]["state"], "held_risk")

    def test_open_case_not_auto_confirmed(self):
        # J3 的 Y3 说明单元判定为可查分，但 F071 个案未结，不能写成已确认
        states = self.result["notify"]["states"]
        self.assertEqual(states["F071|explain"]["state"], "held_adjudication")
        ledger = self.result["calibration"]
        self.assertFalse(any(e["exam"] == "F071" for e in ledger["final"]))
        self.assertTrue(any(e["exam"] == "F071" for e in ledger["withheld"]))

    def test_calibration_uses_only_confirmed(self):
        ledger = self.result["calibration"]
        self.assertEqual(len(ledger["final"]), 1)
        self.assertEqual(ledger["final"][0]["authorized_score"], 72)

    def test_late_evidence_changes_state(self):
        bundle = self.bundle
        before = run_round(bundle, as_of=date(2026, 9, 27))
        # K4 的盲听 09-28 才到：此前 F071 只有一份有效复听
        case = next(c for c in before["review"]["cases"]
                    if (c["exam"], c["item"]) == ("F071", "explain"))
        self.assertEqual(case["state"], "open")
        self.assertEqual(case["missing_relistens"], 1)
        # F078 的授权 09-29 才确认：此前通知仍是已提议
        self.assertEqual(before["notify"]["states"]["F078|respond"]["state"],
                         "proposed_pending")
        self.assertFalse(before["calibration"]["final"])


class CliTest(Fixture):
    def test_cli_commands_run(self):
        import io
        import review_tool
        out = io.StringIO()
        for command in ("structure", "diagnose", "risk", "plan", "notify"):
            with self.subTest(command=command):
                buffer = io.StringIO()
                import contextlib
                with contextlib.redirect_stdout(buffer):
                    code = review_tool.main([str(DATA), command])
                self.assertEqual(code, 0)
                self.assertTrue(buffer.getvalue().strip())
        self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()
