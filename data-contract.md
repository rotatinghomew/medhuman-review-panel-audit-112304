# 资料口径

考务分项满分 100。脚本号识别同一困难度条件，量表改版后只有双方共同的有效分项能比较。配对评分签阅同一个 `note` 时不构成两份独立意见。抽查包含分层概率抽查和登记为 1 的必查，二者的覆盖含义不同；`sent` 表示已抽中未确认完成。复听老师与已知的教学利益、曾读原评分与名额限制见登记。成绩公示在各分项均有有效分时按均分判等级，阈值 70，开放的无争议分项可照常公示；任一替代分可能改变等级时须两名独立复听且分差不大于 8，以复核小组授权选择的成绩为准；无法达成进入仲裁。只在已确定的判决回到校准历史时计为最终结果。

数据表使用 UTF-8 CSV，第一行是字段名。同一业务号的引用指数据字典约定的原始对象；空白表示来源未提供，集合字段由逗号分隔后整体按 CSV 转义。
- `exam.csv` 的字段为 `id`、`student`、`cohort`、`script`、`actor`、`date`、`rubric`、`teacher`。
- `score_scale.csv` 的字段为 `edition`、`item`、`common_item`、`weight`。
- `score.csv` 的字段为 `exam`、`rater`、`item`、`score`、`received`、`kind`。
- `review_sample.csv` 的字段为 `id`、`exam`、`stratum`、`prob`、`stage`、`received`、`rater`。
- `rater_role.csv` 的字段为 `exam`、`rater`、`process`、`note`。
- `notice.csv` 的字段为 `id`、`exam`、`item`、`notice_state`、`date`。
- `availability.csv` 的字段为 `rater`、`eligible_items`、`available`、`seen_exams`、`recuse_teachers`、`capacity`。
- `risk_rule.csv` 的字段为 `cohort`、`item`、`max_bias`、`confidence`、`min_crossings`、`priority`。
- `adjudication.csv` 的字段为 `exam`、`item`、`ordered_on`、`received`、`status`、`authorized_score`。
