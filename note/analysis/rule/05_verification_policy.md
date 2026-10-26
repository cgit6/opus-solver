# 獨立驗證政策

<!-- markdownlint-disable MD013 -->

本文件定義 Acceptance Contract、獨立測試、oracle、native clean build、Reviewer gate 與正式 evidence 的最低要求。測試是否適用由 [`02_role_trigger_matrix.md`](02_role_trigger_matrix.md) 判定；結果狀態依 [`04_evidence_status_and_fingerprint_policy.md`](04_evidence_status_and_fingerprint_policy.md)。

## Acceptance Contract

### VER-CONTRACT-001｜實作前凍結

每個 product／integration CR 都必須在 Developer 開始前有 frozen Acceptance Contract。其內容 owner 是 Independent Tester；Tester 只能把批准的 requirement 與 Design Packet 轉成可觀察判準，不能創造新需求或重大架構。

Contract 至少定義：

- requirement／decision／design trace；
- observable behaviors 與明確 non-goals；
- success、failure、blocked 與 inconclusive 判準；
- critical tests 與最小案例；
- oracle／golden／reference 的來源及獨立性；
- tolerance、numeric/RNG/failure/persistence/replay contract，若適用；
- environment matrix；
- test layers 與 impact matrix；
- N/A 項目、理由與失效條件；
- performance/completion bound，若適用；
- contract change control。

### VER-CONTRACT-002｜Critical tests 優先

在 Developer 開始前，Tester 必須先完成足以固定主要語意的 critical test cases、test vectors 或 characterization cases。需要尚未存在的 integration wiring 才能執行的測試可延後完成，但其輸入、預期結果、oracle 與判定語意必須先凍結。

預期會失敗的 red test 或 characterization evidence 不等於產品已失敗；它們用來證明測試確實涵蓋尚未實作的行為。

### VER-CONTRACT-003｜Contract 變更

Frozen contract 不得為了讓 candidate 通過而直接改寫。發現 requirement 歧義、oracle defect 或 test contract 錯誤時：

1. 停止 verification；
2. 說明是產品語意、設計可實作性或驗證資產問題；
3. 依 `REC-CONTRACT-001` 建立新版本；
4. 重新執行受影響 R0；
5. 依 `EVD-INVALIDATION-001` 使下游 evidence `STALE`。

## 測試資產所有權

### VER-OWNERSHIP-001｜Developer 與 Tester 測試分離

測試分為兩類：

- **Developer-owned self-tests**：由 Developer 建立以協助實作，必須在 CR allowlist 內；不能作 independent gate 的唯一證據。
- **Tester-owned verification assets**：acceptance tests、independent oracle、golden、failure scenarios、formal fixtures；Developer read-only。

Developer 不得修改、停用、放寬或繞過 frozen Tester assets。需要修正時由 Tester依 `VER-CONTRACT-003` 處理，Reviewer 查核變更本身。

### VER-ORACLE-001｜Oracle independence

正式 oracle 不得只是再次呼叫相同 production path、複製相同錯誤公式或以 candidate output 自我生成 expected value。Tester 必須記錄 oracle 的獨立基礎，例如：

- 小案例手算或枚舉；
- 已批准且行為固定的 reference implementation；
- 數學不變量與 metamorphic relation；
- 獨立資料來源或既有可信 artifact；
- 交叉實作 parity，加上已知限制。

無法建立足夠獨立 oracle 時，結果最多為 `INCONCLUSIVE` 或 `INFORMATIVE_ONLY`，除非 Acceptance Contract 明確定義其他可接受判準。

### VER-GOLDEN-001｜Golden 更新

- Expected semantic behavior 改變：必須回 requirement/design，取得必要使用者批准並建立新 contract。
- 純格式、路徑或 loader 的機械修正：Tester 可修改，Reviewer 必須審查。
- 任何 golden/oracle 變更都產生新 `verification_assets_id`，舊 evidence 依影響轉為 `STALE`。

不得以「candidate 是新的」作為更新 golden 的理由。

## 驗證分層

### VER-LAYERS-001｜最低測試層級

依 trigger 選用下列層級，適用項目不得只由單一 happy-path E2E 取代：

1. requirement／contract tests；
2. unit tests；
3. component tests；
4. Python/C++ parity 或 binding boundary tests；
5. process/lifecycle/failure tests；
6. persistence、delivery、actual-input 與 replay tests；
7. end-to-end tests；
8. non-functional tests；
9. affected regression；
10. integration/final full regression。

每個最小 observable behavior 都必須有獨立、可辨識的驗證目標。全域 coverage 百分比不能代替 requirement/state/failure coverage。

### VER-ATOMIC-001｜原子 CR 驗證

原子 CR 至少執行：

- frozen acceptance/critical tests；
- 該 vertical slice 的最小獨立測試；
- impact matrix 指定的 affected regression；
- trigger 要求的 failure、replay、ownership、RNG、numeric、persistence、binding 或 migration tests。

結果必須能區分本 CR failure、既有 baseline failure、environment failure 與 dependency skip。

### VER-FINAL-001｜Integration／final 驗證

Integration CR 或 final delivery target 至少執行：

- 完整 regression；
- package/install/load 與實際 entrypoint；
- 適用的 Python/C++ boundary、process、failure、replay、actual-input、persistence、migration/rollback；
- constituent CR interaction tests；
- Acceptance Contract 指定的 performance／resource checks；
- delivery manifest 與 exact artifact identity 查核。

Final suite 必須針對 composite `target_id`，不能拼接 constituent CR 的舊 PASS 代替。

## Native clean build

### VER-NATIVE-BUILD-001｜強制觸發

符合 `TRG-CPP-001` 的每個正式 candidate 都必須由 Independent Tester clean rebuild。每個 candidate target 至少 build 一次，不是每個 test case 重編一次。

即使 production source/build recipe 沒變、只有 test/oracle 修正，本專案仍要求重新 clean build，產生新的 verification run 並重新執行受影響 gate。

### VER-NATIVE-BUILD-002｜Clean build 程序

Tester 必須：

1. 取得 immutable `target_id` snapshot。
2. 建立 target-specific、全新且空的 build directory。
3. 記錄 OS/architecture、compiler、stdlib、Python/ABI、native dependencies 與 flags。
4. 不引用 Developer／Integrator object files、CMake cache、`.so`、wheel 或既有 Python import process。
5. 按 frozen build recipe 建置一次。
6. 對實際 wheel／`.so`／executable 建立 `artifact_id`。
7. 在 fresh process 中載入並記錄實際 load path 與 artifact identity。
8. 讓該 run 的所有適用 suite 使用同一份 artifact。
9. 將 build/load/result 摘要與外部 evidence references 記入 manifest。

可以重用 toolchain image、dependency download 或 package registry cache；不得重用 target object、build-system cache、既有 native artifact 或未證明 cache key 完整的 compiled cache。

### VER-ARTIFACT-001｜Exact artifact promotion

通過 final gate 的 artifact 必須直接以相同 bytes／`artifact_id` 交付。Developer build 與 Integrator assembly build 都不是正式交付 artifact；正式 artifact 由 Tester clean build 產生並保管 identity。

若 release pipeline 必須重建，重建結果是新 `artifact_id`，必須重新執行正式 verification 與 Reviewer gate。

## Environment matrix

### VER-ENV-001｜全域最低環境

- Linux 是正式 authority environment。
- WSL 可作適當 smoke 或開發驗證，但不能在未經 contract 指定時取代 Linux final gate。
- 所有專案宣告支援的 Python 版本都必須進 regression matrix；CR 可依影響增加環境，不可擅自縮減全域支援。
- Native CR 依風險使用 debug/sanitizer 與 release configuration；compiler、ABI、flags 由 build contract 鎖定。
- 環境缺失使用 `BLOCKED_ENV`，不能推論產品 PASS/FAIL。

若專案尚未定義正式 C++ build contract，相關 CR 保持 design／roadmap blocked；不得由 Tester 臨時選一套工具鏈並宣稱正式驗收。

### VER-SANITIZER-001｜Sanitizer

觸及 buffer、pointer、ownership/lifetime、binding conversion、layout、shared memory、concurrency、cleanup 或 native crash 的 C++ CR，sanitizer 是 mandatory check。

純數學邏輯且未改 memory boundary 時，Tester 可依 frozen applicability matrix 提出 `N/A`，Reviewer確認後生效。Sanitizer 沒有報錯不能取代功能、contract 或 parity tests。

## 長時間測試與 Watchdog

### VER-LONG-RUN-001｜Tester 自主執行

Tester 可依 Acceptance Contract 自主執行 slow、full-corpus、long replay、stress 與 formal performance tests，不需要普通 gate 以外的額外許可。只有 CR 或使用者明確定義的 stop point 可以限制啟動時機。

### VER-WATCHDOG-001｜Test-only watchdog

Tester 可以用 watchdog 防止測試環境永久掛住，但必須：

- 將 watchdog bound 與產品 completion bound 分開；
- 保存當時可取得的 process、output 與 environment 事實；
- 預設將 watchdog termination 判為 `INCONCLUSIVE`；
- 不把測試工具 kill 自動歸因為 product timeout、deadlock 或 crash。

## Tester 與 Reviewer gate

### VER-TESTER-001｜Tester 結論邊界

Tester 報告觀察事實、重現條件、狀態六軸、target/artifact IDs、environment、適用性及 evidence references。Tester不得在缺乏證據時猜 root cause，也不得修改 production code。

Test collection 成功、只有 skipped tests、coverage 達標、prototype 成功或 Developer 自測成功，都不能單獨形成 Tester PASS。

### VER-REVIEW-001｜Reviewer 三個 gate

- `R0`：pre-implementation design、acceptance、critical tests、oracle、slice 與 trigger 一致性。
- `R1`：原子 candidate 的 diff、provenance、implementation quality、Tester evidence 與同 target 技術接受。
- `R2`：integration/final target、constituent CR、build/package/load、migration/rollback、限制及 reproducible delivery。

Reviewer 是 read-only。可以重跑 targeted 或高風險證據，但不必無差別複製 Tester 全套；Reviewer 必須核對 Tester 方法與 target/artifact identity，不能只看摘要中的綠色結果。

### VER-REVIEW-002｜Finding taxonomy

```text
S0_CRITICAL
S1_MAJOR
S2_REQUIRED_QUALITY_CORRECTION
S3_NOTE
QUESTION
```

`S0`、`S1`、`S2` 與未回答 `QUESTION` 都阻止 gate；`S3_NOTE` 不要求本 CR 修正，但必須保留。不得使用 conditional PASS 隱藏 required finding。

### VER-EVIDENCE-001｜外部證據當下核對

正式 Tester 與 Reviewer 必須在 gate 當下檢查同一 evidence reference，並在各自 report 記錄 target/artifact 及查閱時間。外部內容不保存、不要求 digest，後續可取得性與稽核限制依 `EVD-EXTERNAL-001`。

## Prototype

### VER-PROTOTYPE-001｜只保留報告的 Prototype

Prototype 在 Developer 開始前仍需 Architect 規格、Tester testability review 與 Reviewer 方法審查。由於本專案選擇不在 repository 保留 prototype source，prototype report 必須標記：

```yaml
admissibility: INFORMATIVE_ONLY
reproducible: false
```

允許用途只有架構討論與假設生成；禁止用於 acceptance gate、parity oracle、production artifact、可維護性／ABI／undefined behavior 證明或 implementation completion claim。

若 prototype 結論成為 production 必要依據，必須建立正式 roadmap unit，以 production source、frozen contract 與完整驗證重新取得證據。
