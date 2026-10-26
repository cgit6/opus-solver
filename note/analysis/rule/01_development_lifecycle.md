# 開發生命週期與 Gate

<!-- markdownlint-disable MD013 -->

本文件定義從 `system_redesign` 到 CR 關閉的唯一狀態機。角色權限依 [`00_governance_authority.md`](00_governance_authority.md)，狀態軸與 fingerprint 依 [`04_evidence_status_and_fingerprint_policy.md`](04_evidence_status_and_fingerprint_policy.md)。

## 三個治理層級

### LIFE-LAYER-001｜Design、roadmap、CR 分層

流程分為三層，不得以任一層代替另一層：

1. **Design 層**：`system_redesign` 保存需求、決策、候選、實驗與未決項。
2. **Roadmap 層**：將已足以實作的設計切成有順序、依賴與驗收摘要的 unit。
3. **CR 層**：在一個已批准 unit 的固定範圍內完成實作、獨立驗證與接受。

文件內容完整不等於設計已批准；設計已批准不等於 production 已實作；測試曾成功不等於目前 target 已通過。

### LIFE-DESIGN-001｜Design readiness

Roadmap unit 只有在下列條件成立時才可標記 `READY_FOR_USER_APPROVAL`：

- observable objective、in-scope 與 out-of-scope 明確；
- applicable D/P/G 及其狀態可追溯；
- 沒有會改變該 unit 目的或 acceptance 的未決議題；
- 架構責任、主要 contract、ownership/lifecycle、failure/replay 邊界足以實作；
- 可以形成一個可獨立驗證的 vertical slice；
- 已列依賴 unit、risk profile、驗收摘要與預期 Integrator trigger。

尚未滿足時只能保持 `DRAFT` 或 `BLOCKED`，不得為追求進度建立可實作 CR。

### LIFE-UNIT-001｜一 Unit、一 CR、一垂直 Slice

固定粒度為：

```text
1 roadmap unit = 1 CR = 1 independently verifiable vertical slice
```

垂直 slice 必須能以自身及已通過依賴完成 build、執行與驗證。若 Python、C++、binding 或 process component 分開後任一方無法被驗證，這些 component 必須在 roadmap 時合併為同一 unit；不得先讓不可驗證的半成品取得 PASS，再期待 Integrator 補齊。

一個較大能力必須拆成多個 independently acceptable unit。跨 unit 組合產生新 target 時，另建 integration unit／CR。

## Roadmap 生命週期

### LIFE-ROADMAP-001｜Roadmap unit 狀態

Roadmap unit 使用下列狀態，不使用 evidence 的 `PASS`：

```text
DRAFT
READY_FOR_USER_APPROVAL
APPROVED
CR_CREATED
IN_PROGRESS
BLOCKED
COMPLETED
SUPERSEDED
```

只有使用者可使 unit 從 `READY_FOR_USER_APPROVAL` 進入 `APPROVED`。一個 unit 同時只能有一個 active CR。unit 被語意更新取代時，舊 unit 標記 `SUPERSEDED`，不得覆寫其歷史內容。

### LIFE-ROADMAP-002｜G0–G5 的定位

`system_redesign` 中的 G0–G5 是 program capability gates，用於安排整體遷移順序；它們不是單一 CR 的 phase，也不因文件核對、prototype 或個別測試完成而自動通過。

同一 G 可以包含多個 unit 與 CR。依賴前一 G production capability 的 unit，在前置 gate 未滿足時不得進入 implementation；不依賴的研究或設計工作可以進行，但不能藉此宣告後續 G 完成。

## CR 狀態機

### LIFE-CR-001｜正常 phase

CR 的正常 phase 為：

```text
CR_OPEN
→ BASELINE_DRAFTING
→ BASELINE_REVIEWED
→ READY_FOR_IMPLEMENTATION
→ IMPLEMENTING
→ CANDIDATE_READY
→ VERIFYING
→ TECHNICALLY_ACCEPTED
→ USER_ACCEPTANCE_PENDING
→ DELIVERY_AUTHORIZED
→ DELIVERED
→ CLOSED
```

`phase` 只表示流程位置。測試 outcome、阻塞、waiver、N/A 與 evidence validity 必須寫在獨立狀態軸，不得塞入 phase 名稱。

### LIFE-CR-002｜Suspension

任何 phase 都可以附加 suspension：

```yaml
suspension:
  active: true
  cause: BLOCKED_ENV | SKIPPED_DEPENDENCY | DEFERRED | USER_DECISION_REQUIRED | RULE_CONFLICT
  resume_phase: <phase>
```

解除 suspension 後，PM 必須重新核對 baseline、target 與 evidence validity；不得自動恢復先前 PASS。

### LIFE-CR-003｜建立 CR 的前置條件

PM 只有在下列條件全數成立時才能建立 CR：

- roadmap unit 已由使用者批准；
- unit 尚無其他 active CR；
- unit 符合 `LIFE-UNIT-001`；
- 依賴 unit 已達到該 unit 所要求的狀態；
- 可建立精確 `decision_bundle_id`；
- 已套用 trigger matrix 並指派相互獨立的角色 instance；
- workspace、write lease 與允許路徑已記錄。

CR 建立後不得悄悄擴張 objective、scope、acceptance 或重大架構。需要擴張時停止 CR，回到 design／roadmap 並取得新的使用者批准。

## Pre-implementation gate

### LIFE-R0-001｜R0 輸入順序

Pre-implementation 固定順序如下：

1. PM 忠實整理使用者批准的 unit、scope、decision bundle 與需求來源。
2. Architect 產出 Design Packet。
3. Tester 將 requirement 與 design 轉成 Acceptance Contract、critical tests、oracle plan 與 environment matrix。
4. Architect 檢查 acceptance 是否可實作；Tester 檢查 design 是否可觀察與可驗證。
5. 兩者修訂完成後形成 sealed pre-implementation packet。
6. Reviewer 對同一 packet fingerprint 執行 R0。
7. PM 僅在 R0 正式 PASS、所有必要 ACK 齊全且沒有 blocker 時 freeze baseline。

此順序用來避免 Architect 等 acceptance、Tester 又等完整 design 的循環。Tester 不得在 Acceptance Contract 創造新產品需求；遇產品歧義依 `GOV-USER-001` 交使用者決定。

### LIFE-R0-002｜R0 通過條件

Reviewer 的 R0 至少確認：

- requirement、decision bundle、Design Packet 與 Acceptance Contract 可雙向追溯；
- objective、scope 與 observable behavior 一致；
- slice 可獨立 build 與驗證；
- interface、data/control flow、ownership/lifecycle、failure/replay 與 compatibility 足夠明確；
- oracle、tolerance、環境與 critical tests 可以區分成功、產品失敗與環境阻塞；
- prototype、production 與正式 evidence 邊界清楚；
- 沒有 material TBD 留給 Developer 自行決策。

R0 沒有 conditional PASS。任一必要項未滿足即回到內容 owner 修正並產生新 packet fingerprint。

## Implementation 與 R1

### LIFE-IMPLEMENT-001｜實作條件

Developer 只能在 phase 為 `READY_FOR_IMPLEMENTATION`、baseline 為 frozen 且持有 exclusive write lease 時開始。Developer 必須只修改 CR allowlist 內的 production paths 與 Developer-owned self-tests。

完成後 Developer 提交 candidate manifest、變更摘要、build recipe、自測結果、已知限制與 rollback 資訊。Developer 自測不能構成正式 Tester evidence。

### LIFE-R1-001｜候選驗證順序

候選驗證固定為：

```text
Developer candidate
→ seal target_id（以及適用時 artifact inputs）
→ Independent Tester verification
→ Independent Reviewer R1
→ technical gate evaluation
```

Tester 失敗後由 Developer 修正會產生新 target，舊 Tester evidence 與尚未完成的 Reviewer gate 轉為 `STALE`。Reviewer 發現 production defect 時也必須回 Developer，修正後重新經 Tester；不得只重跑 Reviewer。

若 finding 指向 Acceptance Contract、oracle 或 Design Packet 錯誤，必須 reopen pre-implementation baseline，不能直接改測試讓現有 candidate 通過。

### LIFE-GATE-001｜技術接受公式

一個 CR 只有在 `EVD-GATE-001` 公式成立時可進入 `TECHNICALLY_ACCEPTED`。PM 只負責核對公式與記錄 transition，不是 PASS 的簽署者。

`TECHNICALLY_ACCEPTED` 之後必須停在 `USER_ACCEPTANCE_PENDING`，等待使用者依 `GOV-CLOSE-001` 作最終產品接受。

## Integration 與 R2

### LIFE-INTEGRATION-001｜何時必須另建 Integration CR

下列任一情況成立時，必須建立使用者批准的 integration unit／CR：

- 組合兩個以上獨立 CR；
- 組合後的 source tree 與任何已驗收 target 不同；
- 新增或改變 package、native artifact、entrypoint、config、schema、generated artifact、migration 或 rollback；
- Python/C++、process、persistence、replay 等跨邊界行為只在組合後可觀察；
- 最終交付 artifact 尚未形成。

如果單一原子 CR 的已驗收 target 本身就是 delivery target，且 `TRG-INTEGRATION-001` 判定 Integrator 不適用，該 CR 可直接進 final acceptance。

### LIFE-INTEGRATION-002｜Integrator 邊界

Integrator 只能在獨立 workspace 中按已批准順序套用已雙 PASS、`CURRENT` 的 constituent targets，並產生 composite manifest。Integrator 可以處理設計唯一決定的純機械組裝，不得：

- 解決有多種語意選擇的 conflict；
- 寫入新產品邏輯；
- 修改 contract、test、oracle 或 acceptance；
- 將 assembly smoke 宣告為正式 PASS。

出現語意 conflict 或 integration defect 時，建立新的 correction／integration-fix unit，按完整 R0、implementation、Tester、R1 流程處理。

### LIFE-R2-001｜Final delivery gate

Integration CR 形成新 `target_id` 後，Tester 對該 target 執行 clean build 與 final suite，Reviewer 對同一 target／artifact 執行 R2。R2 必須核對 constituent CR、composition、build/package/load provenance、entrypoint、migration/rollback、waiver、限制與重現方式。

R2 雙 PASS 不會取代使用者最終接受。

### LIFE-DELIVERY-001｜Delivery 不等於 Production release

本流程的 `DELIVERED` 表示使用者已接受的 source snapshot、適用時的 exact verified artifact、delivery manifest、限制與重現方式，已放到 roadmap unit 指定的核准位置並完成 custody 記錄。

除非 roadmap unit 明確把 commit、push、tag、publish 或 production cutover 列入 scope，否則上述外部操作不是 CR 關閉條件。若列入 scope，PM 只能在使用者最終接受後依 `GOV-CLOSE-001` 授權 Integrator 執行既定機械操作；任何重建或內容改變都產生新 target/artifact 並重新驗證。

## 失敗、設計缺口與重新開啟

### LIFE-ROUTING-001｜問題路由

| 發現位置 | 問題類型 | 必須路由 |
| --- | --- | --- |
| Roadmap 前 | 需求／重大架構缺口 | `system_redesign` 與使用者決策 |
| Unit 準備 | Applicable P 未收斂 | 保持 `DRAFT`／`BLOCKED` |
| Tester testability | 無法觀察、無 oracle | Architect／Tester 修 pre-packet |
| Reviewer R0 | design／acceptance 不一致 | 回內容 owner，重做 R0 |
| Developer | local detail 不足 | Architect 補 Design Packet，受影響 R0 重跑 |
| Developer | 需改需求／重大架構 | suspension，回 design／roadmap／使用者 |
| Tester | 產品行為錯誤 | Developer 修正，新 target，重做 Tester/R1 |
| Tester | 環境不可用 | `BLOCKED_ENV`，不得判產品 PASS/FAIL |
| Reviewer R1 | production defect | Developer 修正後先重做 Tester |
| Reviewer R1 | test／contract gap | reopen baseline，相關 evidence `STALE` |
| Integration | 語意 conflict | 新 correction unit／CR |
| Reviewer R2 | delivery/provenance defect | Integrator 重組或新正式 fix CR |

### LIFE-REOPEN-001｜已關閉 CR 不覆寫

已關閉 CR 後發現 defect 或需求改變，建立 linked roadmap unit／CR；不得改寫舊 CR 的歷史結論。只有修正純轉錄錯誤時可新增 correction event，且原內容仍須可追溯。

## 關閉條件

### LIFE-CLOSE-001｜可關閉條件

PM 只有在以下條件全部成立時才能關閉 CR：

- approved scope 已完成，沒有未處理 blocker 或 required finding；
- technical gate 正式通過，或使用者已建立有效 waiver 並明確接受風險；
- 所有被採用 report 已 ACK，fingerprint 與 evidence 狀態一致；
- delivery target 已明確，適用時是 Tester 驗證過的 exact artifact bytes；
- 使用者已作最終產品接受；
- CR ledger、限制、waiver、rollback 與後續工作已完整連結。

關閉狀態只能是：

```text
CLOSED_ACCEPTED
CLOSED_ACCEPTED_WITH_WAIVER
CLOSED_CANCELLED
```

`BLOCKED`、`FAILED`、`PARTIAL`、`DEFERRED` 或 `INCONCLUSIVE` 不得重新命名為完成。
