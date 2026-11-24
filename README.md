# 模拟会谈评分的组合异常诊断与成绩复核

模拟会谈的交叉评分、盲听抽查和成绩公示回执。 数据不含真实学生、患者或就诊记录。数据表在 `data/`，业务字段和交换约定见 [资料口径](data-contract.md)。

在 Python 3.11 下可直接清点资料和检查表结构。统计环境使用 `requirements.txt` 中锁定的版本，可在虚拟环境中一次安装后离线使用。

```sh
python3 -m pip install -r requirements.txt
python3 inspect_bundle.py data
python3 -m unittest discover -s tests -v
```

资料检查入口只读，输出每张表的记录数，读取到不符合清单的表时退出。空白字段按资料口径解释。

## 诊断与复核工具

`review_tool.py` 是每轮可以接着用的诊断和成绩复核入口，按量表版次划分轮次，默认处理最新一轮：

```sh
python3 review_tool.py data structure            # 交叉结构与记录完整性
python3 review_tool.py data diagnose             # 分歧检验（三种候选办法）
python3 review_tool.py data risk                 # 批次风险判定与单元划分
python3 review_tool.py data plan                 # 复听名额安排与仲裁线索
python3 review_tool.py data notify               # 成绩通知状态与校准留档
python3 review_tool.py data report --format json # 全部结果的 JSON（留档）
python3 review_tool.py data risk --round R1      # 复查历史轮次
python3 review_tool.py data plan --as-of 2026-09-27  # 只用该日期前收到的证据
```

### 各环节的口径

- **structure**：按场次和分项核对考生、剧本、评分员与量表的交叉。角色登记重复、配对评分签阅同一份记录、抽中复听但未完成（`sent`）的场次不算已有独立复核；复听员资格与分项不符的盲听记录不计入证据；评分员×剧本图的空缺交叉格保留疑问。
- **diagnose**：三种候选办法互相印证——A 双向固定效应（初评分 ~ 评分员 + 剧本）、B 场内配对差分（剧本效应自然消去）、C 独立盲听锚点（概率抽查按 1/prob 加权，必查与无登记个案单列不外推）。报告哪些差异可估计、区间多大、哪些因缺少交叉只能保留疑问。
- **risk**：按 `risk_rule.csv` 登记的年级×分项批次规则逐评分员判定。置信区间整体越出 ±max_bias 为确认越界；点估计越界但区间跨界为待证（先锁住，安排定向复听）；点估计在界限内为可查分；交叉数不足只能保留疑问。锁定只覆盖该评分员在该批次内实际评分的场次与分项，不一并判无效。
- **plan**：任一替代分可能改变等级（均分过 70 的判定翻转）时须两名独立复听且分差不大于 8；复听员须覆盖所涉分项、未见过旧评分、不涉及报名时的课程老师回避，并受名额限制。一次复听能支持哪些分项由量表共同分项决定（本轮 R1 场次跨版只支持 listen 与 explain）。每条建议安排标明用途：判清评分员差异、补出个人成绩，或两者都需要；名额不足时明示仍差的独立证据；两名复听员分差不支持结案的交仲裁。
- **notify**：现行成绩以获得授权的判决为准；无争议分项按期通知；被锁分项与未结裁决保持暂扣；未结的个案不因整体异常消失而写成已确认。校准留档只计已确定的判决，未确认成绩不更新评分员校准数据。`--as-of` 可回放后到证据对分项风险和待发布成绩的影响。

### 目录

- `examreview/`：工具包（读取、量表、结构、模型、风险、名额、通知、报告）。
- `review_tool.py`：命令行入口。
- `inspect_bundle.py`：资料包结构清点（只读）。
- `tests/`：格式边界与业务规则测试。
