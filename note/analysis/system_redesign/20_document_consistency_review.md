# 20｜本輪文件修正與審核紀錄

紀錄日期：2026-10-24。範圍是有效設計文件的一致性、研究證據歸檔及進度時序，不是新增設計決策、正式實作或架構驗收。

本章 R1–R7 是「本輪文件修正項目」，與 [原七個討論單元 1–7](README.md#七個討論單元的進度)、[D01–D80 決策](design_decisions.md) 分屬不同編號。修正 PASS 不表示七個討論單元全部完成，也不增加新的 D 編號。

## 逐項修改與審核流程

本輪由獨立文件 editor 修改、另一位只讀 reviewer 審查，root 再全文確認；當項通過後才指派下一項，有補充便留在同項修訂。R1–R7 各有一次正式獨立審查 PASS，並經 root 全文確認 PASS；不把 editor 自查當成獨立審查，也不虛增測試或審核輪次。

| 修正項目 | 修正摘要與權威說明 | 核對結果 |
| --- | --- | --- |
| R1｜算法錯誤政策 | 路線及需求基線同步 D79–D80：算法非預期錯誤停止整場；正常不可行、Python 保存錯誤及未知退出分開。見 [15](15_task_failures_and_result_storage.md#已確認的異常處理要求)。 | 獨立審查 PASS、root 全文確認 PASS；不把普通保存錯誤擴大成全場停。 |
| R2｜架構基線與比較維度 | D35 確曾選定、目前是重新評估基線；排程責任／語言、程序／執行緒拓撲、binding／IPC 三維可組合。見 [14](14_python_cpp_invocation_and_failure_replay.md#架構狀態與比較維度)。 | 獨立審查 PASS、root 全文確認 PASS；未選新架構或正式 binding 版本。 |
| R3｜共享資料連動範圍 | 分清不變共享需求與原 D74–D77 機制；新候選偏離具體機制須列差異待確認，原決定未自動撤銷。見 [08](08_cpp_invocation_and_shared_memory.md#不變需求與原交接基線)。 | 獨立審查 PASS、root 全文確認 PASS；不把原交接機制全降為未定，也不硬鎖機制卻宣稱可任意換拓撲。 |
| R4｜保存責任與語言 | 同步保存、算法／addAct 不 I/O、主管只收摘要／路徑不變；Python 是有效舊基線，候選須列 D18 完整返回與所有權、錯誤映射差異。見 [07](07_history_return_and_storage.md#已確認交付需求與保存基線)。 | 獨立審查 PASS、root 全文確認 PASS；C++ 輸出元件不等於算法負責文件，測過不等於採用。 |
| R5｜證據歸檔與進度時序 | [19](19_architecture_candidate_experiments.md) 及 [輕量歸檔](evidence/architecture_candidates/README.md) 保存 411 份來源；分開當時研究、後續候選實測與本次只讀核對，更新有效進度。 | 獨立審查 PASS、root 全文確認 PASS；第 1／2／4 單元有候選證據但未選型，第 3 單元設定政策已定待 API／交付，第 5／6／7 仍待討論。 |
| R6｜執行層級與替換影響 | task、邏輯工作鏈、實體 host、thread 與舊基線 worker 分開；D34 約束同鏈，D38 按 task 判定，D40 新拓撲替換範圍／時機待確認。見 [14 名詞表與例子](14_python_cpp_invocation_and_failure_replay.md#執行名詞與替換範圍)、[15 事件案例](15_task_failures_and_result_storage.md#十個事件案例)。 | 獨立審查 PASS、root 全文確認 PASS；不把重開 thread／物件當原生環境恢復，不默選立即或排空後退休。 |
| R7｜原因留存要求與機制界線 | D25 強需求是範圍內 Python 軟體保存失敗的原因與 task 事後可查；產生原因、通知、持久保存不同。二次軟體失敗／留存前退出保障待確認。見 [15 六情境對照](15_task_failures_and_result_storage.md#保存錯誤原因的留存界線)。 | 獨立審查 PASS、root 全文確認 PASS；不降成最佳努力，不把 worker-first artifact 升格正式方案，不擴大 D26 排除。 |

期間 root 退補的精確度細節留在當項處理：R5 的 startup 樣本限定為每個「拓撲／題目尺寸／執行單元數」組合一次，不依 workload／saver 重複；R7 的「整個儲存不可寫」限定為 D26 已排除硬體／資源故障造成，不能把路徑／權限／序列化等軟體問題因全域影響而排除。這些不另算新增修正項目或額外正式審查輪次。

七項通過後，root 全文收尾另發現 14 的兩處小補丁，逐句退回 editor：

- 14 約 106 行的「下一輪比較」改為連到 19 已有候選研究，保留歷史隔離基線及有效持有／回收界線。
- 14 約 109 行 D31 的「記錄與恢復」改為依觀察事實記錄、退出分類與後續處置按既有政策及待議架構細化，不預設自動重跑或中途恢復。

兩個補丁各自經 reviewer 獨立重審及 root 確認 PASS，未改決策、架構或實驗。

最後全文總審第一輪結果為 FAIL：D31 權威決策表的理由格漏同步 14:109，仍留「記錄與恢復」的過度承諾。其餘語意、數字、來源及 1,510 個非 Markdown 檔案核對均 PASS。root 已退回此處，editor 定點同步 D31 理由格並補記退補經過；第二輪獨立全文總審已完成，reviewer 正式 PASS，root 最後回歸亦 PASS。第一輪跨文件回歸的 FAIL 紀錄及前述 R1–R7 各一次正式審查 PASS 的歷史均保留，不是新增決策。

## 已做的只讀核對與證據限制

下表記錄本輪 editor／reviewer／root 的核對範圍；計算及 SHA 可只讀檢查，完整政策語意仍由人工審閱，沒有自動驗證所有政策的工具。

| 核對項目 | 已核對結果與限制 |
| --- | --- |
| 決策與文件結構 | D01–D80 在決策表各一次，4 個 YAML 區塊可解析；新增本章後的文件／本機連結數另依下節實跑結果記錄。不是正式設定 schema 或實作驗收。 |
| 18 設定範例 | root 靜態獨立重算一般範例 120＋2＝122，精確配對 1＋1＝2，並核對 SENT 現有 `sent01.yaml`、`sent02.yaml` 兩題。這是讀範例與現有資料的計數，不是執行正式 reader、支援 API 或 solver。原 80／2／122 歷史推演口徑仍見 [18](18_experiment_configuration_and_task_expansion.md#本輪推演證據與限制)。 |
| 新研究歸檔 | [manifest](evidence/architecture_candidates/manifest.json) 對應 411 份原始檔、4,487,283 bytes；403 份 identity 逐位元一致，8 份刻意截斷負例以 base64 保存、解碼後大小／SHA 一致，不冒稱有效 JSON 實體副本。三批原稽核中的 35 筆歷史 source SHA 亦一致。 |
| 候選 raw 摘要 | 只讀獨立重算 48 組／240 計量批次統計及 8 個 sampled-PSS 摘要，核對 48 補充案例與 8 個 CDELS runs 的原回放摘要（6 unique inputs、每 run 12 checks），與原稽核一致。不是重新跑 CDELS、真 threaded port 或完整故障驗收。細項及當時口徑見 [19](19_architecture_candidate_experiments.md)。 |
| 未重跑的歷史內容 | 未執行原型、編譯、故障注入或原 audit；未重讀／重比未封存的 2,336 份大型完整輸出。該批 1,194,241,580 bytes 全內容核對是當時原稽核的證據，不是本輪重新驗證。 |
| 17 原型來源 | [原研究附件](evidence/invocation_comparison/README.md) 的 `build_probe.py`、`experiment.py`、`probe.cpp` 三份來源 SHA 未變；不改 16／17 的歷史方法或測量數字。 |
| 正式專案與使用者變更 | root 以本輪開始時 1,510 個 tracked 非 Markdown 檔案的 SHA 比較，全部不變；這是本機只讀核對，沒有封存 1,510 份副本。未動正式 code／config／dependencies／註冊；保留使用者既有 log → note/log 搬移及新增 note/analysis/rule 變更，未 commit／push。新增研究原型副本與只讀歸檔工具不冒稱正式功能實作。 |

## 新增本章後的結構核對

本章與 README／DD／13 引用新增後，實跑結構驗證器 PASS：33 份納入檢查的 Markdown、729 個本機連結、80 個決策、4 個可解析 YAML 區塊，錯誤為 0。第一層主文件為 22 份，與包含附件及相鄰路線的檢查範圍不同。`git diff --check` 亦 PASS；上述結構檢查不代替人工語意總審。

可在專案根目錄做以下只讀歸檔核對及 diff 檢查：

```bash
.venv/bin/python note/analysis/system_redesign/evidence/architecture_candidates/verify_archive.py
.venv/bin/python note/analysis/system_redesign/evidence/architecture_candidates/verify_archive.py --compare-originals
git diff --check
```

`--compare-originals` 須原 `/tmp` 來源仍存在；只核對已歸檔內容／解碼後原位元，不重驗未封存的大輸出。原實驗腳本會寫檔，不是只讀驗證器；未來重跑只能依 [歸檔限制](evidence/architecture_candidates/README.md#安全核對與重跑限制) 複製到全新 tmp，不能在原件或歸檔原位執行。

## 仍未替使用者決定的事項

新架構組合、正式 API／binding、資料與結果所有權、布局／精度、未知退出判定、安全收尾及退休策略、原因留存時序與二次失敗／退出保障、DTO／正式格式、算法支援查詢及統計規則，均保留原未定狀態；詳見 [13](13_open_questions.md)。D25 強需求、D40 已定原則與待確認的新拓撲映射、D79–D80 算法錯誤停止整場不因本紀錄改動。

本章所記錄的 PASS 僅限本輪文件收斂及上述只讀核對，不代表架構定案、正式 G2／G3 通過、真 CDELS 併發驗收、功能實作完成或批准開始遷移。
