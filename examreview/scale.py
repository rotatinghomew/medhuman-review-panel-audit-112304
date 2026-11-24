"""量表版次与共同分项：决定跨版比较和一次复听能支持哪些分项。"""


class Scale:
    """score_scale 表的查询视图。"""

    def __init__(self, rows):
        self._by_edition = {}
        for row in rows:
            self._by_edition.setdefault(row.edition, {})[row.item] = row

    def editions(self):
        return sorted(self._by_edition)

    def items(self, edition):
        """该版次的全部分项（按表内顺序）。"""
        return list(self._by_edition.get(edition, {}))

    def weight(self, edition, item):
        row = self._by_edition.get(edition, {}).get(item)
        return row.weight if row else None

    def common_item(self, edition, item):
        row = self._by_edition.get(edition, {}).get(item)
        return row.common_item if row else ""

    def comparable_items(self, edition_a, edition_b):
        """两个版次间可比较的分项。

        同一版次内全部分项可比；跨版次时只有双方都登记了同一个
        共同分项（common_item 非空且一致）的分项才可比较。
        """
        items_a = self._by_edition.get(edition_a, {})
        items_b = self._by_edition.get(edition_b, {})
        shared = []
        for item, row_a in items_a.items():
            if edition_a == edition_b:
                shared.append(item)
                continue
            row_b = items_b.get(item)
            if row_b and row_a.common_item and row_a.common_item == row_b.common_item:
                shared.append(item)
        return shared

    def relisten_supported_items(self, exam_edition, review_edition):
        """一次复听结果能支持的分项，由量表共同分项登记决定。

        复听按 review_edition 量表执行；对 exam_edition 的场次而言，
        只有两版共同分项对齐的分项才能采用这次回听结果。
        """
        return self.comparable_items(exam_edition, review_edition)
