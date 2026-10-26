# 角色與驗證 Trigger Matrix

<!-- markdownlint-disable MD013 -->

本文件是角色啟用及最低驗證要求的唯一來源。PM 依客觀條件套用 trigger，角色不得自行宣告自己不適用。技術 profile 到當期 D/P/G 的映射由後續的 `07_project_verification_profile.md` 定義。

## 通用規則

### TRG-BASE-001｜正式 Product CR 的基本角色

每個正式 product 或 integration CR 都必須指派：

- PM／Process Lead；
- Architect；
- Developer；
- Independent Tester；
- Independent Reviewer。

Conditional Integrator 依 `TRG-INTEGRATION-001` 啟用。即使變更看似局部，Architect 仍負責確認 Design Packet 與既有設計一致；若不需要新增設計，Design Packet 可記錄「沿用哪些批准 contract」，不能直接略過 R0。

純治理文件建置、角色規則修正及尚未授權實作的設計討論不冒充 product CR，適用其自己的文件審查流程。

### TRG-NO-SELF-NA-001｜角色不得自行退出

角色啟用與 Integrator N/A 由 PM 依本矩陣機械判定。角色可提交「條件不成立」的證據，但不能自行批准 N/A。

個別 test/check 的 N/A 由 Tester 依 frozen applicability matrix 提出、Reviewer 核對；有爭議時依 `EXC-CONFLICT-001` 交使用者。

### TRG-CLASSIFY-001｜變更分類責任

在 R0 前，PM 必須逐項記錄變更是否觸及：

- Python behavior／API／CLI／config；
- C++ source／header／binding／ABI；
- build／package／install／load path；
- RNG／determinism／numeric precision；
- process／thread／IPC／shared memory；
- ownership／lifetime／cleanup；
- failure classification／stop／retry／replay；
- persistence／actual input／result delivery；
- migration／compatibility／rollback；
- performance／resource bound；
- test／oracle／golden；
- security-sensitive parsing、path 或 external command。

未知或混合類型採 fail-closed，啟用較嚴格要求。

## Trigger 表

### TRG-PYTHON-001｜Python behavior

**客觀條件**：Python production source、公開 API、CLI、config parsing、task planning、persistence 或 result handling 改變。

**最低要求**：

- contract／unit／affected regression；
- entrypoint 與錯誤路徑測試；
- serialization、persistence 或 replay 測試，若相關；
- Reviewer R0 與 R1；
- package/install smoke，若 distribution 內容改變。

### TRG-CPP-001｜C++／binding／native build

**客觀條件**：任何 `.cpp/.cc/.cxx/.h/.hpp`、binding source、native generated source、compiler flag、ABI、native dependency、native build recipe、package/install/load path 改變，或 composite target 重新組合上述內容。

**最低要求**：

- Tester 依 `VER-NATIVE-BUILD-001` clean rebuild；
- fresh process load 並記錄實際 load path／artifact identity；
- contract、boundary、error propagation 與 affected regression；
- Reviewer 核對 build provenance；
- 交付 exact verified artifact bytes。

Developer 不得自行宣告 native clean build N/A。

### TRG-MEMORY-001｜Memory／ownership 風險

**客觀條件**：buffer、pointer/reference、container invalidation、ownership/lifetime、shared memory、binding conversion、layout、concurrency、native crash 或 cleanup 路徑改變。

**最低要求**：

- sanitizer build/run；
- lifetime、invalid input、cleanup 與故障路徑測試；
- Reviewer 明確核對 ownership model。

純數學邏輯且未穿越 memory boundary 時，Tester 可提出 sanitizer `N/A`，只有 Reviewer 核對後才生效。

### TRG-RNG-001｜RNG 與可重現性

**客觀條件**：seed derivation、RNG state、draw order、parallel scheduling 對 RNG 的影響、algorithm stochastic behavior 或 replay inputs 改變。

**最低要求**：

- seed/state contract tests；
- 相同輸入與受保證模式的 replay／parity；
- task 隔離及 draw-order 影響分析；
- 不受保證模式的明確限制；
- Reviewer 查核 oracle 獨立性。

### TRG-NUMERIC-001｜數值、轉換與算法語意

**客觀條件**：numeric type、precision、rounding、conversion、objective、constraint、feasibility、incremental update 或 algorithm state 語意改變。

**最低要求**：

- boundary／type rejection／precision tests；
- independent oracle 或已批准 parity baseline；
- smallest non-trivial cases 與 adversarial cases；
- 若觸及 C++，同時套用 `TRG-CPP-001`。

### TRG-PROCESS-001｜Process、thread、IPC 與 lifecycle

**客觀條件**：process/thread topology、scheduling responsibility、IPC、worker supervision、stop/cancel、crash handling、shared resource lifecycle 或 cleanup 改變。

**最低要求**：

- state/event sequence 測試；
- crash、partial delivery、unknown exit、stop timing 與 cleanup；
- actual input 及已知事實留存；
- race／deadlock／resource leak 風險審查；
- 適用時套用 `TRG-MEMORY-001` 與 integration CR。

### TRG-PERSISTENCE-001｜Persistence、result delivery 與 replay

**客觀條件**：檔案格式、writer、delivery acknowledgement、actual-input record、result/history storage、replay entrypoint 或保存失敗語意改變。

**最低要求**：

- schema／round-trip／atomicity 或 partial-write 測試；
- 成功、失敗及未確認交付區分；
- replay 使用指定 input 的重現測試；
- compatibility、migration 與 rollback，若舊資料受影響。

### TRG-MIGRATION-001｜Migration／compatibility／rollback

**客觀條件**：舊 config/data/API、storage schema、entrypoint、package layout 或部署方式需遷移。

**最低要求**：

- 明確 supported/unsupported matrix；
- 可回復 migration 與 rollback rehearsal；
- 資料保存與失敗中斷情境；
- 不可逆 migration 必須先由使用者明確批准並定義 backup/forward recovery。

### TRG-PERFORMANCE-001｜正式效能要求

**客觀條件**：Acceptance Contract 包含 latency、throughput、memory、startup、scale 或相對 performance 門檻，或變更有顯著 regression 風險。

**最低要求**：

- 固定 workload、環境、warm-up、重複次數與統計方法；
- correctness gate 先於 performance；
- timeout/watchdog 與產品完成 bound 分開；
- 原始結果可由證據連結識別，報告記錄限制。

Tester 可依 contract 自主執行長時間與 full-corpus 測試，不需另向 PM 或使用者取得普通 gate 授權。

### TRG-PROTOTYPE-001｜Prototype

**客觀條件**：為回答架構或可行性問題而建立非 production prototype。

**最低要求**：

- Architect 先定義問題、變數、成功／失敗判準與禁止推論；
- Tester 審 testability，Reviewer 審方法；
- Developer 才能實作 prototype；
- 只保存報告、不保留 source 時，結果一律 `INFORMATIVE_ONLY`；
- 不得作 acceptance oracle、production target 或完成聲明。

### TRG-INTEGRATION-001｜Conditional Integrator

下列任一條件成立就必須啟用 Integrator 並建立 integration unit／CR：

- 兩個以上獨立 CR 要組成一個交付；
- final source tree 不等於任何已驗收 target；
- 需要 merge、ordered patch application 或 composite manifest；
- package、native artifact、entrypoint、config、schema、generated artifact、migration 或 rollback 在組合階段形成或改變；
- 跨 Python/C++、process、writer、persistence 或 replay 的行為只有組合後可驗證；
- release/delivery artifact 尚未形成。

只有下列條件全部成立時，PM 才能記錄 Integrator `N/A`：

- 單一 CR、單一 Developer、無 merge/conflict；
- 已雙 PASS target 就是 delivery target；
- 沒有後續 rebuild、repackage、config、entrypoint、schema 或 migration 變更；
- 適用的正式 artifact 已在相同 target 下被 Tester clean build、load、test 並由 Reviewer 核對。

### TRG-FINAL-001｜Final／integration regression

原子 CR 執行 acceptance、專屬測試及 impact matrix 的 affected regression。Integration CR 或 final delivery target 必須執行完整 regression，以及所有被觸發 profile 的跨邊界測試。

Impact matrix 本身屬 frozen Acceptance Contract 的一部分；不能在候選失敗後縮小範圍來取得 PASS。

## Trigger 衝突與保守原則

### TRG-CONFLICT-001｜多條 trigger 同時成立

多條 trigger 同時成立時取聯集，不以其中較寬鬆者覆蓋較嚴格要求。若要求互相矛盾，流程依 `EXC-CONFLICT-001` 停止並交使用者裁決。

### TRG-CHANGE-001｜分類改變

實作中一旦發現變更類型與 R0 分類不同，Developer 必須停止。PM 重新套用 matrix；新增角色、測試、sanitizer、integration 或使用者 stop point 時，baseline 必須重審，相關 downstream evidence 轉為 `STALE`。
