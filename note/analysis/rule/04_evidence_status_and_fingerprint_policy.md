# 證據狀態與 Fingerprint 政策

<!-- markdownlint-disable MD013 -->

本文件定義所有 report、check、evidence 與 gate 共用的狀態軸、fingerprint 身分及失效規則。任何角色文件都只能引用這些 enum，不得自行建立同義狀態。

## 多軸狀態

### EVD-STATUS-001｜六個正交狀態軸

每個正式 check/evidence 必須同時記錄六個軸：

```yaml
applicability: APPLICABLE | N/A | OUT_OF_SCOPE_BY_DECISION
execution: NOT_RUN | RUNNING | COMPLETED | SKIPPED_DEPENDENCY | BLOCKED_ENV
outcome: NO_VERDICT | PASS | FAIL_PRODUCT | INCONCLUSIVE
disposition: ACTIVE | DEFERRED | WAIVED
validity: CURRENT | STALE | SUPERSEDED | INVALID
admissibility: FORMAL | INFORMATIVE_ONLY | REJECTED
```

這些軸不得壓縮成一個會混淆語意的 `status` 欄位。UI 或摘要可以顯示衍生狀態，但 canonical record 必須保留六軸原值。

### EVD-STATUS-002｜Applicability

- `APPLICABLE`：依 approved scope、trigger 或 contract 必須執行。
- `N/A`：此 check 對該 target 結構上不適用，不代表通過。角色 trigger N/A 由 PM 依矩陣判定；test/check N/A 由 Tester 提出、Reviewer核對。
- `OUT_OF_SCOPE_BY_DECISION`：使用者明確排除，必須引用 user decision ID。

### EVD-STATUS-003｜Execution 與 outcome

- `NOT_RUN`：尚未執行。
- `RUNNING`：仍在執行，不能產生最終 outcome。
- `COMPLETED`：已按記錄方法完成，仍需看 outcome。
- `SKIPPED_DEPENDENCY`：依賴未滿足，不能計為 PASS。
- `BLOCKED_ENV`：環境阻止結論，不能判產品 PASS 或 FAIL_PRODUCT。
- `NO_VERDICT`：尚無結論或不適用。
- `PASS`：觀察結果符合 frozen acceptance。
- `FAIL_PRODUCT`：在有效環境與方法下，產品不符合 acceptance。
- `INCONCLUSIVE`：執行完成或中止，但資料不足以判 PASS/FAIL_PRODUCT。

test-only watchdog timeout 預設是 `INCONCLUSIVE`；只有 Acceptance Contract 已定義產品 completion bound 時，超過該 bound 才能依 contract 判 `FAIL_PRODUCT`。

### EVD-STATUS-004｜Disposition

- `ACTIVE`：依正常 gate 規則處理。
- `DEFERRED`：工作延後；仍未滿足本 CR gate，除非使用者另作 scope 決定並建立後續 unit。
- `WAIVED`：使用者接受未滿足條件的風險；永遠不等於 PASS。

### EVD-STATUS-005｜Validity

- `CURRENT`：仍對應目前被判定的 baseline/target；不表示證據必然正式可採。
- `STALE`：上游 requirement、design、contract、target、artifact 或環境前提已改變。
- `SUPERSEDED`：已有明確的新 report/evidence 取代，舊內容仍保留。
- `INVALID`：產生方式、身分、角色資格或 provenance 違反規則，不能用於任何正式 gate。

### EVD-STATUS-006｜Admissibility

- `FORMAL`：符合角色、方法、fingerprint、ACK 與證據政策，可用於正式 gate。
- `INFORMATIVE_ONLY`：只可形成假設、設計討論或診斷方向。
- `REJECTED`：不接受作任何決策依據，例如 target 不明、角色不獨立或內容無法歸屬。

Prototype 不保留 source 時必須為 `INFORMATIVE_ONLY`，即使 validity 是 `CURRENT` 也不能提升為 `FORMAL`。

## Gate 公式

### EVD-GATE-001｜正式技術雙 PASS

對所有 required、`APPLICABLE` checks，技術 gate 只有在下式成立時才通過：

```text
execution == COMPLETED
AND outcome == PASS
AND disposition == ACTIVE
AND validity == CURRENT
AND admissibility == FORMAL
AND tester.target_id == reviewer.target_id == delivery.target_id
AND tester 與 reviewer 是合格且不同的 role instances
AND 所有被採用 gate reports == ACKNOWLEDGED
AND 沒有未解決 required finding 或 blocker
AND 若存在交付 artifact：
    tester.artifact_id == reviewer.artifact_id == delivery.artifact_id
```

`N/A` checks 必須有合法 applicability decision；它們不需要偽造 `PASS`。`OUT_OF_SCOPE_BY_DECISION` 必須有 user decision。任何 `NOT_RUN`、`RUNNING`、`SKIPPED_DEPENDENCY`、`BLOCKED_ENV`、`FAIL_PRODUCT` 或 `INCONCLUSIVE` 的 required applicable check 都阻止 ordinary technical PASS。

### EVD-GATE-002｜Waiver 不改寫技術事實

有有效 waiver 時：

```text
technical_gate_passed = false
user_risk_accepted = true
```

CR 可以依 `LIFE-CLOSE-001` 成為 `CLOSED_ACCEPTED_WITH_WAIVER`，但不得顯示 `TECHNICALLY_ACCEPTED` 或 ordinary PASS。

## 分層 Fingerprint

### EVD-FP-001｜Fingerprint 類型

正式流程使用以下分層身分：

```text
decision_bundle_id
baseline_id
source_snapshot_id
verification_assets_id
build_recipe_id
runtime_contract_id
target_id
artifact_id
environment_id
verification_run_id
report_fingerprint
```

每個 ID 的 manifest 必須列出組成項、canonical ordering、hash algorithm 與產生者。本輪沒有 generator，執行者必須保留可人工核對的 manifest，不得宣稱機械完整性。

### EVD-FP-002｜Decision bundle 與 baseline

`decision_bundle_id` 固定該 CR 適用的：

- requirement sources；
- `system_redesign` 文件 revision/content identity；
- applicable D IDs 及當時有效描述；
- applicable P IDs、已定部分及仍未定邊界；
- applicable G gate；
- 明確 superseded／excluded decisions；
- 使用者批准 roadmap unit 的 decision ID。

`baseline_id` 至少由下列內容決定：

```text
decision_bundle_id
+ CR Design Packet fingerprint
+ frozen Acceptance Contract fingerprint
+ trigger/applicability matrix fingerprint
```

角色規則只引用 bundle，不把當期 D/P/G 技術語意複製進永久契約。

### EVD-FP-003｜Source、verification、build 與 runtime

- `source_snapshot_id`：product source path、file bytes、mode、symlink target、deletion、submodule revision，以及 scoped production-relevant untracked/generated files。
- `verification_assets_id`：independent tests、oracle、golden、fixture、runner policy 及 impact matrix。
- `build_recipe_id`：build scripts、lock/dependency declarations、compiler/toolchain policy、flags 與 ABI 要求。
- `runtime_contract_id`：entrypoint、config schema/default、package manifest、load policy 及 runtime-relevant generated metadata。

Canonical manifest 必須使用 repo-relative path 並排序；不得納入 mtime、absolute workspace path 或 report/evidence 檔。production-relevant untracked/generated file 未分類時 fail-closed。

### EVD-FP-004｜Target、artifact、environment 與 run

```text
target_id = H(
  baseline_id,
  source_snapshot_id,
  verification_assets_id,
  build_recipe_id,
  runtime_contract_id
)
```

- `artifact_id`：exact wheel、`.so`、executable 或交付 package bytes 的身分。
- `environment_id`：相關 OS、architecture、Python、compiler、stdlib、native dependencies 與 runner environment。
- `verification_run_id`：target、artifact、environment、commands、runner version 與執行序列的身分。

正式交付採用 Tester 驗證過的 exact `artifact_id`。重建即產生新 artifact，必須重新正式驗證。

### EVD-FP-005｜Dirty worktree 身分

不要求每個 candidate 都先 commit。若 snapshot 尚未 commit，manifest 至少記錄：

- Git `HEAD`；
- tracked diff/patch identity；
- scoped untracked/generated file path 與 content identity；
- deleted／renamed path；
- submodule revision；
- build/runtime inputs。

只記 commit SHA 而忽略 dirty、untracked 或 generated inputs 不足以形成正式 `source_snapshot_id`。

### EVD-FP-006｜無循環依賴

身分與證據的方向固定為：

```text
artifact manifest → fingerprint
evidence/report → target/artifact fingerprint
gate decision → target/artifact fingerprint + evidence/report IDs
```

Tester evidence、Reviewer report、gate decision、CR phase 或 report ACK 不得被納入其所驗證的 `target_id` 或 `artifact_id`。

## Evidence reference 與可取得性

### EVD-EXTERNAL-001｜當下見證型證據

本制度允許沒有 content digest、可覆寫或日後失效的外部 evidence reference 支撐當時 gate，條件是：

1. evidence manifest 記錄 reference、執行摘要、target/artifact/environment/run IDs 與時間；
2. Tester 在自己的正式 report 明確聲明已檢查該 reference；
3. Reviewer 在 gate 當下獨立開啟並確認同一 reference 與相同 target/artifact；
4. 兩份 gate report 均依 `REC-ACK-001` ACK。

這種證據的保證來自當下兩名獨立角色的見證，不是內容的永久不可變性。reference 日後不可用時：

- 不自動改寫已關閉 CR 的歷史 gate；
- PM 在再稽核時記錄 `evidence_availability: UNAVAILABLE`；
- 該 reference 不能支撐新的 gate、重新驗證或衍生 target；
- 文件不得宣稱仍可獨立重播原始輸出。

Evidence availability 另記：

```text
AVAILABLE | UNAVAILABLE | NOT_RECHECKED
```

availability 不取代六軸狀態。

## 失效與重驗

### EVD-INVALIDATION-001｜Downstream invalidation

下列任一輸入發生相關變更，受影響的下游 target、report、evidence、N/A、waiver 與 gate 必須轉為 `STALE` 或重新確認：

- requirement、scope、D/P/G、Design Packet；
- Acceptance Contract、applicability、test、oracle、golden；
- production source、generated source、build recipe、compiler/ABI/dependency；
- package、entrypoint、config、schema、load path；
- constituent CR、composition order 或 integration base；
- migration、rollback、runtime environment；
- exact artifact bytes。

PM 只作 dependency-impact 判定與記錄；有技術爭議時由 Architect/Tester/Reviewer提出分析，產品或規則歧義交使用者。

### EVD-INVALIDATION-002｜修改後的重驗範圍

- Production target 改變：Tester 重新驗證後 Reviewer 重新 R1/R2。
- Acceptance/test/oracle 改變：reopen baseline；即使 production source 未變，仍依既定政策重新 clean build 並建立新 run。
- Build/package/artifact 改變：產生新 artifact，完整 native/delivery gate 重跑。
- 純 report 整理改變：report ACK 失效，但若 target inputs 未變，不自行使 target stale。
- 只有 external evidence link 失效：依 `EVD-EXTERNAL-001` 處理 availability，不改寫歷史；需要新判斷時重新產生 evidence。

### EVD-INVALIDATION-003｜INVALID 與 STALE 不混用

`STALE` 表示曾有效對應舊 target，但上游已變。`INVALID` 表示證據從一開始或因治理違規就不可採，例如：

- 作者角色不合格或不獨立；
- target/artifact 身分缺失或互相矛盾；
- PM 改寫結論且內容 owner 拒絕 ACK；
- Reviewer 對自己實質修改的 revision 給予 gate；
- 使用 Developer build 冒充 Tester clean build；
- 把無 source prototype 當正式 oracle。

`INVALID` 不能靠 waiver 變成 `FORMAL` 或 PASS。
