# 治理、權限與角色分離

<!-- markdownlint-disable MD013 -->

本文件定義治理層級及所有角色都必須遵守的權限邊界。技術設計、驗證方法或 CR schema 的細節分別由其他政策定義。

## 角色集合

### GOV-ROLE-001｜固定六角色

本流程只定義以下六種角色：

1. `PM_PROCESS_LEAD`
2. `ARCHITECT`
3. `DEVELOPER`
4. `INDEPENDENT_TESTER`
5. `INDEPENDENT_REVIEWER`
6. `CONDITIONAL_INTEGRATOR`

Python、C++、RNG、process、persistence、replay、migration 等是專業 profile，不是額外治理角色。同一角色可有多個具不同 profile 的 instance，但不因此取得其他角色的權限。

### GOV-ROLE-002｜永久單角色綁定

一個 agent instance 在本專案內只可綁定一種角色。不得在同一專案中先以 Developer 修改候選，再切換成 Tester 或 Reviewer 驗收該候選。

若角色 instance 必須更換，PM 必須建立 custody transfer 紀錄，包含原 instance、新 instance、原因、時間、未完成工作與已交接 artifact。角色更換不會讓既有證據自動保持 `CURRENT`；應依 `EVD-INVALIDATION-001` 做影響判定。

### GOV-SEPARATION-001｜強制獨立性

同一 CR 的 Developer、Independent Tester 與 Independent Reviewer 必須是三個不同 agent instance。以下組合不得由同一 instance 兼任：

- 產品實作者與正式 Tester；
- 產品實作者與正式 Reviewer；
- 正式 Tester 與正式 Reviewer；
- Integrator 與該 integration target 的正式 Tester 或 Reviewer。

Architect 不得實作其正式設計的 production code 或 prototype code。需要 prototype 時仍由 Developer 在獨立 CR 中實作；無 source 的 prototype 依 `VER-PROTOTYPE-001` 只能作資訊性參考。

## 決策權與文件所有權

### GOV-USER-001｜使用者唯一決策權

只有使用者可以：

- 核准或變更需求、產品 scope 與產品語意；
- 核准重大架構、跨模組 contract、ownership/lifecycle、failure/replay 與 compatibility/migration 取捨；
- 核准 roadmap unit 進入實作；
- reopen 已批准的設計決策；
- 宣告 `OUT_OF_SCOPE_BY_DECISION`；
- 建立 waiver；
- 作最終產品接受及接受風險。

角色可以提出選項、證據與建議，不能把自己的建議記成使用者決定。

### GOV-AUTH-001｜內容權威矩陣

| Artifact／決策 | Accountable authority | 實體 writer | 獨立核對者 |
| --- | --- | --- | --- |
| 原始需求、產品取捨 | 使用者 | PM 忠實整理 | 使用者 |
| `system_redesign` 技術內容 | Architect | Architect | Reviewer；重大取捨由使用者 |
| roadmap unit 與狀態 | 使用者核准／PM 管理 | PM | Reviewer 可提出異議 |
| CR、phase、gate ledger | PM | PM | 依機械規則；Reviewer 可提出異議 |
| CR Design Packet 內容 | Architect | PM 寫入 report | Architect ACK、Reviewer R0 |
| Acceptance Contract 內容 | Tester | PM 寫入 contract/report | Architect 查可實作性、Reviewer R0 |
| independent tests/oracle/golden | Tester | Tester | Reviewer |
| production source 與 Developer self-tests | Developer | Developer | Tester、Reviewer |
| Tester verification 結論 | Tester | PM 寫入 report | Tester ACK、Reviewer 獨立判斷 |
| Reviewer finding／gate 結論 | Reviewer | PM 寫入 report | Reviewer ACK |
| composite assembly／delivery manifest | Integrator；N/A 時為 Developer | 同內容 owner | Tester、Reviewer |
| waiver／最終接受 | 使用者 | PM 忠實記錄 | 以 user decision ID 錨定 |

「內容 owner」與「實體 writer」必須分開記錄。PM 寫入 CR report 不代表 PM 成為報告結論的作者。

### GOV-PM-WRITE-001｜PM-only managed area

以下位置在流程運作時只有 PM 可寫：

- `note/analysis/system_redesign/implementation_roadmap.md`
- `note/analysis/change_records/`

其他角色提供結構化內容與證據引用，由 PM 寫入。正式 gate report 必須依 `REC-ACK-001` 由內容 owner 讀回並確認；未 ACK 的 PM 整理稿不得作為 gate 證據。

PM 不得：

- 改寫角色結論、嚴重度、限制或保留意見；
- 自行創造需求、設計、root cause 或技術 PASS；
- 把不同 target 的 Tester 與 Reviewer PASS 合併；
- 用流程推進權取代使用者或技術角色的決策權。

### GOV-DESIGN-WRITE-001｜受控 living design

`system_redesign` 是受控 living design。Architect 只有在以下條件同時成立時才可修改既有技術主題文件：

1. 有明確 reopened issue 或尚未收斂 P 項；
2. PM 記錄本次允許修改的 file allowlist；
3. 修改不冒充使用者尚未作出的產品或重大架構決策；
4. 新 baseline 依生命週期重新審查與批准。

PM 可機械維護索引、狀態與 roadmap 引用，但不得代替 Architect 改寫技術語意。

## 流程權限

### GOV-PASS-001｜技術接受雙鑰

PM、Architect、Developer 或 Integrator 都無權單獨宣告技術接受。正式技術接受必須由 Independent Tester 與 Independent Reviewer 依 `EVD-GATE-001` 對相同 target 形成雙 PASS。

### GOV-CLOSE-001｜最終接受與關閉

技術雙 PASS 只能把 CR 推進到 `TECHNICALLY_ACCEPTED`。只有使用者完成最終產品接受後，PM 才可記錄 `DELIVERY_AUTHORIZED` 與關閉 CR。

若使用者以 waiver 接受風險，PM 必須使用明確的「accepted with waiver」結論，不得把未通過的技術 gate 改寫成 ordinary PASS。

外部 commit、push、tag 或 publish 只有在使用者已接受該 CR 且該操作位於核准 scope 內時，PM 才可指示 Integrator 機械執行。PM 與 Integrator都不得自行擴張目的地、版本或發布內容。

### GOV-FAIL-CLOSED-001｜Fail-closed

缺少必要輸入、角色、fingerprint、ACK、正式證據、同 target 雙 PASS 或使用者 stop-point 決定時，流程必須停止在目前 phase。不得以沉默、推測、暫時成功、測試未跑或「看起來沒問題」代替通過。

## 工作區與 write lease

### GOV-WORKSPACE-001｜角色隔離工作區

正式執行採以下隔離模型：

- PM 使用 documentation workspace 維護 roadmap 與 CR。
- 同一時間只有一名 Developer 或 Integrator 持有 product snapshot 的 exclusive write lease。
- Tester 從候選的 immutable snapshot 建立獨立 verification workspace 與全新 build directory。
- Reviewer 使用 read-only snapshot；若需重跑命令，必須在自己的隔離環境執行。
- Integrator 使用獨立 integration workspace，只作已核准 patch 的機械組裝。

兩個 writer 不得同時修改同一 product snapshot。遇到未知 dirty file、非 allowlist 路徑或 ownership 重疊時，持有者必須停止並交 PM 判定。

### GOV-WORKSPACE-002｜非機械保證聲明

本輪不實作 worktree wrapper、lease service、ACL 或 CI ownership check。`GOV-WORKSPACE-001` 與 `GOV-PM-WRITE-001` 是規範性限制；每份 CR 必須記錄實際 workspace、lease holder 與隔離方式，不得宣稱工具已防止違規。

## 禁止自我批准

### GOV-NO-SELF-APPROVAL-001｜作者不能批准自己的產物

任何角色都不得讓自己產出的內容單獨滿足正式 gate。具體包括：

- Architect 的 Design Packet 需要 Tester testability review 與 Reviewer R0；
- Developer 自測不能取代 Tester PASS；
- Tester 的 test/oracle 與結果需要 Reviewer 核對；
- Integrator 的 assembly check 不能取代 final Tester／Reviewer gate；
- PM 的完整性計算不能代替技術或使用者接受。

Reviewer 若對候選提交實質 patch，即失去審查該 revision 的資格；修正後必須由另一名合格 Reviewer 審查。
