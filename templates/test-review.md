# [接口或行为名称] 用例评审

评审范围：[本轮需要确认的接口、行为或变更]
源码版本：[revision]

## 接口说明

- 接口作用：[一句话说明]
- 输入：[关键输入]
- 成功结果：[调用方能观察到的结果]
- 失败结果：[调用方能观察到的错误]
- 不负责：[相邻领域负责的行为]

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `AREA-01` | - [ ] 当[前置状态]，执行[操作] | [可直接观察的结果] | [用户或系统会遇到的具体问题] | P0 |
| `AREA-02` | - [ ] 当[边界或错误输入]，执行[操作] | [拒绝、回滚、恢复或状态保持] | [错误输入可能造成的具体问题] | P1 |
| `AREA-03` | - [ ] [尚未明确的场景] | 待确认：[需要 Reviewer 决定的结果] | [不确认会产生的行为歧义] | P1 |

## 本轮需要确认

- [最需要 Reviewer 判断的预期或边界]
- [优先级存在争议的用例，或无]
- [缺少可观测结果的用例，或无]

<!--
Authoring rules:
- Keep one independently observable behavior per physical row.
- Keep the row self-contained and use plain product language.
- The case ID is the only Test Point ID; preserve it when editing the row.
- Start the scenario with `- [ ]`; change it to `- [x]` only when a matching `TEST-MAP` exists.
- Do not add approval, coverage, or other automation statuses.
- Do not include test paths or implementation details.
- Present changed rows and stop for explicit review confirmation before generating test code.
-->
