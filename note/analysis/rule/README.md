# 多 Agent 重構治理規則

<!-- markdownlint-disable MD013 -->

本目錄是 OptiForge 系統重構的流程治理唯一權威來源。它定義角色、權限、生命週期、Change Record（CR）、證據、驗證及例外處理；產品需求與技術語意仍以 [`../system_redesign/`](../system_redesign/) 為準。

## 文件狀態

- `document_set_id`: `RULESET-REFACTOR-GOVERNANCE`
- `document_set_version`: `1.0.0-draft`
- `language`: 說明使用繁體中文；檔名、ID、欄位名與 enum 使用英文。
- `enforcement_level`: `NORMATIVE_PROCESS_ONLY`

`NORMATIVE_PROCESS_ONLY` 表示本規則對參與者具強制性，但本輪不建置 ACL、validator、fingerprint generator、worktree wrapper 或 CI ownership check。任何「只有 PM 可寫」「獨占 write lease」或「隔離工作區」要求，都必須由執行團隊遵守與查核，不能宣稱已由作業系統或工具機械保證。

## 權威鏈

技術語意的權威鏈為：

```text
使用者確認的需求與取捨
→ system_redesign 中的有效決策及未決項
→ roadmap unit 釘住的 decision bundle
→ CR-scoped Design Packet 與 Acceptance Contract
→ implementation target
```

流程語意的權威鏈為：

```text
使用者明確裁決
→ 本目錄的共通政策
→ 角色契約
→ CR 實例與 gate 紀錄
```

下游文件只能具體化上游內容，不能悄悄改寫上游。發現衝突時適用 `EXC-CONFLICT-001`，先停止而不是自行選一份文件繼續。

## 閱讀順序與唯一責任

1. [`00_governance_authority.md`](00_governance_authority.md)：角色集合、權限、分離與工作區規範。
2. [`01_development_lifecycle.md`](01_development_lifecycle.md)：從設計收斂到 CR 關閉的狀態機與 gate。
3. [`02_role_trigger_matrix.md`](02_role_trigger_matrix.md)：依變更類型啟用角色與驗證 profile。
4. [`03_change_record_and_handoff_policy.md`](03_change_record_and_handoff_policy.md)：CR、report、handoff、ACK 與封存政策。
5. [`04_evidence_status_and_fingerprint_policy.md`](04_evidence_status_and_fingerprint_policy.md)：多軸狀態、fingerprint 與失效規則。
6. [`05_verification_policy.md`](05_verification_policy.md)：獨立驗證、測試分層與 native clean build。
7. [`06_waiver_defer_and_conflict_policy.md`](06_waiver_defer_and_conflict_policy.md)：waiver、defer、scope 排除與衝突處理。
8. `07_project_verification_profile.md`：專案技術 profile 對 D/P/G 與驗證要求的映射；在後續階段建立。
9. `code_style.md`：程式碼共通政策，不是角色；在後續階段建立。
10. `roles/`：六份角色契約；在後續階段建立。
11. `templates/`：CR 與報告的 normative schema；在後續階段建立。

共通定義只能存在於其唯一責任文件。角色文件可引用 stable rule ID，不得複製 enum、gate 公式、fingerprint 定義、waiver 規則或 CR schema。

## 規範用語

- 「必須」：違反即不得通過相關 gate。
- 「不得」：禁止行為；發生後相關證據至少為 `INVALID`，並依影響回退流程。
- 「應」：預設要求；偏離時必須留下理由與 Reviewer 判斷。
- 「可以」：在其他強制條件仍成立時允許。

## Stable ID

| Prefix | 唯一用途 |
| --- | --- |
| `GOV-*` | 治理權限與角色分離 |
| `LIFE-*` | 生命週期、gate 與 phase transition |
| `TRG-*` | 角色及驗證觸發條件 |
| `REC-*` | CR、report、handoff 與封存 |
| `EVD-*` | 證據、狀態、fingerprint 與失效 |
| `VER-*` | 測試及獨立驗證政策 |
| `EXC-*` | waiver、defer、scope 與衝突 |
| `PROF-*` | 專案 verification profile |
| `STYLE-*` | 程式碼風格政策 |
| `ROLE-*` | 角色契約 |
| `SCH-*` | Template/schema |
| `RMU-*` | Roadmap unit instance |
| `CR-*` | Change Record instance |
| `AC-*` | Acceptance Contract instance |
| `FP-*` | Fingerprint entry |
| `EV-*` | Evidence entry |
| `RPT-*` | Role report |
| `HO-*` | Handoff entry |
| `WVR-*` | Waiver record |
| `FND-*` | Review finding |
| `BLK-*` | Blocker |

ID 一經引用不得因檔案搬移而重用或改變語意。規則被取代時保留舊 ID 並標記 `SUPERSEDED`，以新 ID 表達新規則。

## 本輪明確邊界

- 不修改產品程式或現有 `system_redesign` 主題文件。
- 不建立虛構 roadmap unit 或 CR。
- 不將 G0–G5、P01–P10 或任何實作狀態宣告為已通過。
- 不保存角色原始訊息或原始測試輸出；CR 保存 PM 整理稿、摘要與證據連結。
- 此保存策略提供流程與決策稽核，不提供永久、可獨立重演的法證級證據。
