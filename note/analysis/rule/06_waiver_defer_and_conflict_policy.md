# Waiver、Defer、Scope 與衝突政策

<!-- markdownlint-disable MD013 -->

本文件定義正常 PASS 以外的治理處置。它不能用來繞過角色身分、證據歸屬或 target 一致性。

## 四種不同概念

### EXC-DISTINCTION-001｜不得混用

| 概念 | 意義 | 決策者 | 是否為 PASS |
| --- | --- | --- | --- |
| `N/A` | 對此 target 結構上不適用 | 角色 trigger：PM 依矩陣；test/check：Tester 提出、Reviewer核對 | 否 |
| `OUT_OF_SCOPE_BY_DECISION` | 使用者明確排除於本次 scope | 使用者 | 否 |
| `DEFERRED` | 適用且仍需要，但延後處理 | 使用者決定 scope 影響；PM 記錄 | 否 |
| `WAIVED` | 條件未滿足，但使用者明確接受風險 | 使用者 | 否 |

任何角色不得用 N/A 隱藏「太慢、太難、環境尚未準備」；不得用 DEFERRED 或 OUT_OF_SCOPE 讓原批准 scope 在未經使用者決定下縮小。

## Waiver

### EXC-WAIVER-001｜唯一授權者

只有使用者可以建立 waiver。角色可以說明未滿足條件、風險、替代措施與建議，但 PM、Architect、Developer、Tester、Reviewer、Integrator 都不能代替使用者接受風險。

PM 只能在收到明確 user decision 後建立 `WVR-*`，不得從沉默、先前類似決定或「使用者應該會接受」推定。

### EXC-WAIVER-002｜必填內容

每個 waiver 至少包含：

```yaml
waiver_id:
cr_id:
authorized_by_user:
user_decision_id:
authorization_timestamp:
unmet_condition:
affected_rule_ids: []
affected_gate_ids: []
target_id:
artifact_id:
scope:
known_risk:
reason:
compensating_controls: []
expiry_condition:
invalidation_conditions: []
replacement_requirement:
```

Waiver 必須窄化到明確 CR、target、gate 與未滿足條件，不能以「之後都不用測」或「整個專案接受風險」作無界授權。

### EXC-WAIVER-003｜不可 Waive 的完整性

以下治理完整性不可 waiver：

- role instance 身分不明或不符合角色；
- Developer、Tester、Reviewer 未分離；
- Tester／Reviewer target 或適用時 artifact 不一致；
- PM 將未 ACK 的整理稿冒充正式 gate report；
- 缺少被判定 target 的基本 identity/provenance；
- Reviewer 審查自己實質修改的 revision；
- 把 `INVALID`／`REJECTED` 證據提升為 `FORMAL`；
- 把 waiver、N/A、blocked、not-run 或 inconclusive 改寫成 PASS。

Waiver 可以接受產品風險、缺少某項正式測試或未達某項門檻，但交付狀態必須是 `CLOSED_ACCEPTED_WITH_WAIVER`，不能是 ordinary technical acceptance。

### EXC-WAIVER-004｜失效

下列任一情況使 waiver 失效並需要使用者重新確認：

- target、artifact、Acceptance Contract 或 scope 改變；
- waived condition、known risk 或 compensating control 改變；
- 到達 expiry condition；
- 新證據顯示風險高於授權時描述；
- waiver 被後續 user decision 撤銷或取代。

PM 必須將失效 waiver 標記 `STALE` 或 `SUPERSEDED`，不得默認沿用。

## Deferred 與 Scope

### EXC-DEFER-001｜Deferred 不等於完成

`DEFERRED` 適用於已知且仍需要的工作。若該工作屬於 CR approved scope，CR 不能 ordinary close，直到：

- 工作完成；或
- 使用者正式改變 scope，並建立必要的後續 roadmap unit；或
- 使用者以 waiver 接受缺口。

PM 必須記錄 owner、reason、dependency、預期重新啟動條件及 linked unit；只有「以後再做」不構成有效 defer plan。

### EXC-SCOPE-001｜Out of scope 需要明確決定

`OUT_OF_SCOPE_BY_DECISION` 必須引用使用者 decision ID，並說明排除的是哪個 observable behavior、為何不屬於本 CR，以及是否仍屬長期需求。

Architect、Developer、Tester 或 Reviewer發現額外工作時只能提出 scope question；在使用者決定前標記 `USER_DECISION_REQUIRED`，不得自行排除。

## 規則與技術衝突

### EXC-CONFLICT-001｜衝突時停止

若兩份 canonical 文件、兩條規則、角色判斷或有效技術決策互相衝突，任何角色都必須：

1. 停止受影響工作；
2. 精確列出衝突的 rule/decision/artifact IDs 與語句；
3. 說明各解讀會影響的 scope、target、evidence 與風險；
4. 保留共同不受影響的已知事實；
5. 交使用者裁決，不自行選較方便的一邊。

PM 記錄 `RULE_CONFLICT` suspension。裁決後更新唯一權威來源，再依 `EVD-INVALIDATION-001` 判定下游失效範圍。

### EXC-DESIGN-REOPEN-001｜重開已批准決策

角色若認為既有設計決策需重開，必須提交 evidence-based reopen request，至少包含：

- 被挑戰的 decision ID 與目前有效語意；
- 新證據或具體矛盾；
- 不重開的風險；
- 可行候選及對既有 unit/CR 的影響；
- 建議 freeze 的工作範圍。

提交 request 不表示已重開。只有使用者可批准 reopen；批准前受影響 CR 保持 suspension，其他不受影響工作可由 PM 依 dependency analysis 繼續。

## Review 爭議

### EXC-APPEAL-001｜Reviewer finding appeal

對 Reviewer finding 有異議時：

1. 原 Reviewer 先依新增證據重新檢查；
2. 若仍有具體技術爭議，可由 PM 指派最多一名第二 Reviewer；
3. 第二 Reviewer 必須符合獨立性並檢查相同 target/finding；
4. 不採多數決，也不得不斷更換 Reviewer 尋找 PASS；
5. 兩者仍衝突時，結果為 `INCONCLUSIVE` 或 `RULE_CONFLICT`，依問題性質交使用者。

Reviewer finding 被新證據解決時，以新 report supersede 舊 report；不得刪除原 finding。

### EXC-NO-SHOPPING-001｜禁止 Reviewer shopping

不得因 Reviewer 給出 `S0`–`S2`、`QUESTION` 或 FAIL 就改找其他 Reviewer，除非依 `EXC-APPEAL-001` 完成一次正式 appeal。第二 Reviewer 的存在不降低原 finding；必須有明確 resolution 或使用者處置。

## Failure 與 Blocked 的誠實紀錄

### EXC-BLOCKED-001｜Blocked 不作產品歸因

`BLOCKED_ENV`、`SKIPPED_DEPENDENCY`、缺少使用者決定或規則衝突只描述目前無法完成 gate，不自動證明產品好壞。解除 blocker 後必須重新檢查 target 與 evidence validity，再從記錄的 resume phase 繼續。

### EXC-FAILURE-001｜不得以管理處置洗掉結果

`FAIL_PRODUCT`、`INCONCLUSIVE`、`INVALID`、`STALE`、`REJECTED` 與 required finding 必須保留原語意。Waiver、scope decision、defer、report supersede 或 CR cancellation 可以決定下一步，但不能改寫曾觀察到的結果。
