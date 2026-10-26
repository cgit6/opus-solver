# Change Record、Report 與 Handoff 政策

<!-- markdownlint-disable MD013 -->

本文件定義 CR 實例如何建立、更新、交接與封存。欄位的 normative schema 會在 `templates/` 建立；本文件只定義紀錄行為與不變量。

## CR 身分與目錄

### REC-CR-001｜命名與唯一性

每個 CR 使用：

```text
CR-YYYYMMDD-NNN-short-name
```

- 日期使用 Asia/Taipei 的建立日期。
- `NNN` 是當日三位數流水號，不得重用。
- `short-name` 使用小寫 ASCII kebab-case，只描述 objective，不放狀態。
- CR ID 一經建立不得因改名、封存或狀態改變而更換。

### REC-CR-002｜一 Unit 對一 CR

每個 CR 必須引用唯一 `roadmap_unit_id`，每個 roadmap unit 同時只能有一個 active CR。CR 只實作該 unit 的一個 independently verifiable vertical slice，適用 `LIFE-UNIT-001`。

integration 工作也必須先有自己的 roadmap unit，不能在其他 CR 的尾端臨時增加 integration scope。

### REC-CR-003｜標準結構

每個 CR 使用固定結構：

```text
note/analysis/change_records/CR-.../
├── change_record.md
├── handoffs.md
├── fingerprint_ledger.md
├── evidence_manifest.md
├── contracts/
│   └── AC-...-vNNN.md
├── reports/
│   └── RPT-...-role-report-type.md
└── waivers/
    └── WVR-....md
```

不得在 CR 內複製 `system_redesign` 全文、產品原始碼、完整測試輸出或大型 binary。CR 保存 frozen contract、PM 整理的角色報告、狀態 ledger、摘要及外部 evidence references。

## 寫入與變更控制

### REC-WRITE-001｜PM-only 寫入

整個 CR 目錄由 PM 管理，適用 `GOV-PM-WRITE-001`。其他角色不得直接新增、修改或刪除 CR 檔案；其內容由 PM 依角色回報整理後寫入。

這是流程限制而非 ACL。PM 必須在 event log 記錄每次寫入的 writer instance、內容 owner、時間與原因。

### REC-APPEND-001｜歷史不可覆寫

以下內容採 append-only 或 versioned 更新：

- event log；
- handoff entries；
- fingerprint entries；
- evidence manifest entries；
- gate decisions；
- role reports；
- Acceptance Contracts；
- waivers。

錯誤內容不得原地消失。修正時新增版本或 correction event，使用 `supersedes` 指向舊 ID，並保留舊檔。`change_record.md` 可以更新 current-state summary，但必須能由 append-only ledger 還原狀態轉移。

### REC-CUSTODY-001｜PM custody transfer

PM 無法繼續履職時，只有使用者可指定替代 PM。接任前必須記錄：

- 原 PM 與新 PM instance；
- 使用者授權 reference；
- transfer time；
- active CR phase、blockers 與未完成 handoff；
- current decision/baseline/target IDs；
- 尚未 ACK 或尚未寫入的報告。

沒有 custody transfer 不得由其他角色臨時接管 CR writer 權限。

## `change_record.md` 邊界

### REC-SUMMARY-001｜Current truth 與索引

`change_record.md` 只保存：

- CR identity、roadmap unit、objective、scope 與 out-of-scope；
- decision bundle 與 requirement/design sources；
- assigned role instances 與 workspace/lease；
- current phase、suspension 與六軸狀態摘要；
- active baseline/target/artifact IDs；
- gate ledger 與被採用 report/evidence/waiver IDs；
- active blockers、findings、限制與下一個 stop point；
- append-only event log；
- completion／cancellation summary 與 archive state。

完整 Design Packet、Acceptance Contract、Tester 結果、Reviewer findings 與 waiver 必須存於其獨立檔案；CR summary 只引用 ID。

### REC-EVENT-001｜事件最小欄位

每個 event 至少記錄：

```yaml
event_id:
event_type:
timestamp:
actor_role:
actor_instance:
previous_phase:
new_phase:
affected_artifact_ids: []
affected_fingerprints: []
reason:
source_reference:
```

狀態重算、證據失效、user decision、waiver、ACK、custody transfer 與 archive 都必須有 event。

## Report 政策

### REC-REPORT-001｜Report ID 與檔案

角色報告使用 CR 內唯一 ID：

```text
RPT-NNN-role-report-type
```

檔案名使用相同 ID 的小寫形式。Report 一旦成為 `ACKNOWLEDGED` 或被 gate 引用便不得原地改寫；修正時新增 report 並以 `supersedes` 連結舊 report。

### REC-REPORT-002｜PM 整理稿是 canonical report

本制度不保存角色原始訊息。PM 根據角色回報建立 canonical report，至少明列：

- `content_owner_role` 與 `content_owner_instance`；
- `file_writer_role: PM_PROCESS_LEAD` 與 PM instance；
- PM 整理時間；
- 輸入 artifact／fingerprint；
- 角色的結論、限制、finding、blocker 與 requested action；
- PM 是否進行語句整理；
- report fingerprint；
- ACK 狀態，若屬正式 gate report。

PM 不得省略會改變結論、風險或後續行動的保留意見。因不保存 raw payload，本制度只能稽核 canonical report 與 ACK，不能獨立比較 PM 整理稿和原始措辭。

### REC-ACK-001｜正式 Gate Report 必須 ACK

Architect Design Packet、Tester testability／verification、Reviewer R0/R1/R2 等會被正式 gate 採用的 report，必須經以下流程：

1. PM 完成 report draft 並計算 `report_fingerprint`。
2. 內容 owner 讀取完整 canonical report。
3. 內容 owner 明確回覆 ACK 該 fingerprint，或列出需要修正的內容。
4. PM 記錄 `ack_by`、`ack_at`、`ack_report_fingerprint`。

只有 ACK fingerprint 與目前 report fingerprint 相同時，report 才是 `ACKNOWLEDGED`。任何改動都使既有 ACK 失效。一般 coordination handoff 不要求 ACK，但仍須記錄內容 owner。

### REC-REPORT-003｜Report 狀態

```text
DRAFT
ACK_PENDING
ACKNOWLEDGED
SUPERSEDED
REJECTED
```

`ACKNOWLEDGED` 只證明內容 owner確認 PM 整理稿，不代表 outcome 是 PASS，也不代表 evidence 為 `CURRENT` 或 `FORMAL`。

### REC-REPORT-004｜Report 與 target 分離

Report fingerprint 不得成為其所審查 `target_id` 的組成。Report 單向引用 target、artifact、evidence IDs；target 變更時 report 可轉為 `STALE`，但不重新計算舊 report 內容來偽裝成新 report。

## Handoff 政策

### REC-HANDOFF-001｜所有正式交接經 PM

正式 handoff 由 PM 記入 `handoffs.md`。角色可以直接澄清技術問題，但沒有記入 handoff 的 artifact、target、requested action 或 stop condition，不能作為 phase transition 的依據。

每筆 handoff 至少包含：

```yaml
handoff_id:
from_role_instance:
to_role_instance:
via_pm: true
timestamp:
input_artifact_ids: []
input_fingerprints: []
requested_action:
required_output_type:
stop_condition:
```

### REC-HANDOFF-002｜接收者先驗證輸入

接收者開始工作前必須確認：

- CR、phase 與 requested action 合法；
- 輸入 artifact/fingerprint 存在且為目前版本；
- 自己是該 CR 已指派的正確角色 instance；
- workspace 與讀寫權限符合角色；
- 沒有未處理 blocker、conflict 或 user stop point。

不符合時回報 blocker，不得自行修補 ledger 後繼續。

## Acceptance Contract 版本

### REC-CONTRACT-001｜Frozen contract 不覆寫

Acceptance Contract ID 使用：

```text
AC-NNN-vNNN
```

`DRAFT` contract 可在 R0 前修訂；一旦 frozen，任何語意變更都建立新版本並以 `supersedes` 指向舊版。PM 必須依 `EVD-INVALIDATION-001` 使受影響 target、evidence 與 gate `STALE`。

拼字或純排版修正若確定不影響 canonical fingerprint，可以 correction event 處理；分類有爭議時視為語意變更。

## Evidence references

### REC-EVIDENCE-001｜只保存摘要與連結

CR 不保存完整原始測試 log、sanitizer output、coverage、binary 或 core dump。`evidence_manifest.md` 保存摘要及外部 URI/path，至少包含：

- evidence ID、producer role/instance；
- target/artifact/environment/run IDs；
- command、working-directory class 與執行時間；
- exit status、狀態六軸與結果摘要；
- external location；
- Tester 與 Reviewer 當下查閱的 reference 與時間；
- 已知保存期限或「未知」；
- related report ID。

不要求 evidence content digest。此選擇的限制依 `EVD-EXTERNAL-001` 明列，任何文件不得宣稱可永久獨立重演原始證據。

## 封存

### REC-ARCHIVE-001｜狀態封存、不搬路徑

CR 完成或取消後保留原 canonical path，不移入其他實體目錄。使用：

```yaml
archive_state: ACTIVE | ARCHIVED
archived_at:
archived_by:
closure_status:
```

封存後不得刪除 report、contract、ledger、waiver 或歷史 reference。後續 defect 依 `LIFE-REOPEN-001` 建立 linked CR。
