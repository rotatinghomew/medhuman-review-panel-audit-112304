"""读取考务交换包为带类型的记录，并做基本校验。"""
import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _date(text):
    """把 YYYY-MM-DD 字符串转成 date；空白返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _int(text):
    text = (text or "").strip()
    return int(text) if text else None


def _float(text):
    text = (text or "").strip()
    return float(text) if text else None


def _list(text):
    """集合字段：逗号分隔，空白表示未提供。"""
    text = (text or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


@dataclass(frozen=True)
class Exam:
    id: str
    student: str
    cohort: str
    script: str
    actor: str
    date: date
    rubric: str
    teacher: str


@dataclass(frozen=True)
class ScaleItem:
    edition: str
    item: str
    common_item: str  # 空白表示改版后无共同分项
    weight: float


@dataclass(frozen=True)
class Score:
    exam: str
    rater: str
    item: str
    score: int
    received: date
    kind: str  # first / blind


@dataclass(frozen=True)
class ReviewSample:
    id: str
    exam: str
    stratum: str
    prob: float
    stage: str  # sent / completed
    received: date
    rater: str


@dataclass(frozen=True)
class RaterRole:
    exam: str
    rater: str
    process: str  # paired / independent
    note: str


@dataclass(frozen=True)
class Notice:
    id: str
    exam: str
    item: str
    notice_state: str  # published / held / proposed
    date: date


@dataclass(frozen=True)
class Availability:
    rater: str
    eligible_items: tuple
    available: date
    seen_exams: tuple
    recuse_teachers: tuple
    capacity: int


@dataclass(frozen=True)
class RiskRule:
    cohort: str
    item: str
    max_bias: float
    confidence: float
    min_crossings: int
    priority: int


@dataclass(frozen=True)
class Adjudication:
    exam: str
    item: str
    ordered_on: date
    received: date
    status: str  # open / sent_to_arbitration / confirmed
    authorized_score: int  # 仅 confirmed 时有值


class Bundle:
    """一个考务交换包的全部表。"""

    def __init__(self, root):
        root = Path(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        raw = {name: list(csv.DictReader((root / name).open(encoding="utf-8", newline="")))
               for name in manifest}
        self.exams = {r["id"]: Exam(r["id"], r["student"], r["cohort"], r["script"],
                                    r["actor"], _date(r["date"]), r["rubric"], r["teacher"])
                      for r in raw["exam.csv"]}
        self.scale = [ScaleItem(r["edition"], r["item"], r["common_item"].strip(),
                                _float(r["weight"]))
                      for r in raw["score_scale.csv"]]
        self.scores = [Score(r["exam"], r["rater"], r["item"], _int(r["score"]),
                             _date(r["received"]), r["kind"])
                       for r in raw["score.csv"]]
        self.samples = [ReviewSample(r["id"], r["exam"], r["stratum"], _float(r["prob"]),
                                     r["stage"], _date(r["received"]), r["rater"])
                        for r in raw["review_sample.csv"]]
        self.roles = [RaterRole(r["exam"], r["rater"], r["process"], r["note"])
                      for r in raw["rater_role.csv"]]
        self.notices = [Notice(r["id"], r["exam"], r["item"], r["notice_state"],
                               _date(r["date"]))
                        for r in raw["notice.csv"]]
        self.availability = [Availability(r["rater"], tuple(_list(r["eligible_items"])),
                                          _date(r["available"]), tuple(_list(r["seen_exams"])),
                                          tuple(_list(r["recuse_teachers"])),
                                          _int(r["capacity"]))
                             for r in raw["availability.csv"]]
        self.risk_rules = [RiskRule(r["cohort"], r["item"], _float(r["max_bias"]),
                                    _float(r["confidence"]), _int(r["min_crossings"]),
                                    _int(r["priority"]))
                           for r in raw["risk_rule.csv"]]
        self.adjudications = [Adjudication(r["exam"], r["item"], _date(r["ordered_on"]),
                                           _date(r["received"]), r["status"],
                                           _int(r["authorized_score"]))
                              for r in raw["adjudication.csv"]]

    def editions(self):
        """资料中出现的量表版次，按场次日期排序（旧到新）。"""
        first_seen = {}
        for exam in self.exams.values():
            first_seen.setdefault(exam.rubric, exam.date)
            first_seen[exam.rubric] = min(first_seen[exam.rubric], exam.date)
        return [ed for ed, _ in sorted(first_seen.items(), key=lambda kv: kv[1])]

    def latest_edition(self):
        return self.editions()[-1]
