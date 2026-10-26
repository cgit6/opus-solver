# 架構候選實驗：輕量原始證據歸檔

封存日期：2026-10-24。設計摘要、數字口徑及未驗收邊界見 [19](../../19_architecture_candidate_experiments.md)。本附件保存已做研究的來源，不是正式架構、依賴版本、API、故障政策或 G2／G3 驗收結果。

## 來源與保存範圍

| 子目錄 | 原暫存來源（provenance） | 保存內容 |
| --- | --- | --- |
| `gate1/` | `/tmp/solver-architecture-gate1-vOJPeS` | 原型來源、README、環境、smoke、完整稽核摘要及三批 `output-*/results.json`。 |
| `gate2/` | `/tmp/solver-architecture-gate2-wE6cmX` | 故障控制原型、README、環境、smoke、24／48／72 案例各階段稽核摘要及九批結果摘要。 |
| `comparison/` | `/tmp/solver-architecture-comparison-F5nHlQ` | 原 README／REPORT、原型與分析來源、`combined_audit.json`、`benchmark_results.json`、環境／reference SHA／smoke、兩批補充案例的輸入／指派／事件／controller report／錯誤與輕量結果，以及真 CDELS、原始 global RNG、clean prefork、唯讀保護的腳本與結果。 |

共 411 份原始檔、原始內容 4,487,283 bytes：403 份按原位元保存；8 份刻意截斷且無尾端換行的負向結果檔，以原檔名加 `.base64` 保存原始位元。它們有意不是有效 JSON；解碼後的大小／SHA 才是原始內容，不能把編碼文字冒稱原 JSON 實體檔。

[manifest.json](manifest.json) 列出逐檔 `source_relative_path`、`archive_relative_path`、原絕對路徑、`encoding`、`original_sha256`、`decoded_size` 與尾端換行狀態；原 JSON 內的絕對路徑也原樣保留，都是當時來源，不是假裝仍可用的歸檔路徑。環境及編譯命令見 [comparison 環境](comparison/perf_environment.json)、[gate1 環境](gate1/environment.json)、[gate2 環境](gate2/environment.json)，獨立 reference 來源雜湊見 [reference hashes](comparison/perf_reference_hashes.json)。當時用 Python 3.12.3、g++ 13.3.0、暫存 pybind11 3.1.0、Linux／WSL2；不因此選定專案正式依賴。

刻意不封存：`.so`、可執行檔、core、`pydeps`、`__pycache__`、`real-cpp-build` 等生成物；`performance-measured` 約 1.2 GiB 完整輸出、其他 performance／memory 輸出樹、gate1／gate2 逐 task 大份輸出及 prefork 五份完整輸出。相關摘要、路徑、當時雜湊及稽核結果保留。原暫存資料與既有 [16](../../16_process_lifecycle_experiment.md)、[17](../../17_invocation_comparison_experiment.md) 研究來源未修改。

## 安全核對與重跑限制

**原始腳本會寫檔。不得直接在本歸檔或原暫存來源執行、編譯或重跑任何原型／原 audit。** 特別是 `comparison/audit_and_analyze.py` 會寫 `combined_audit.json`，原 README 的原位重檢命令只屬當時工作記錄，不能當成本歸檔的安全檢查方式。

本目錄唯一新增的只讀工具可在專案根目錄執行：

```bash
.venv/bin/python note/analysis/system_redesign/evidence/architecture_candidates/verify_archive.py
.venv/bin/python note/analysis/system_redesign/evidence/architecture_candidates/verify_archive.py --compare-originals
```

第二行額外讀原 `/tmp` 檔案，來源已消失時不能執行。兩者只讀 manifest、內容與 SHA，不載入原型、不編譯、不求解、不故障注入、不寫結果；也**不重新核對未封存的 2,336 份完整輸出**。原稽核的數字是當時證據，不是本次歸檔重新計算大份內容的結果。

日後若獲准重跑，須另開一項工作，依以下順序：

1. 用 `mktemp -d` 建立全新暫存目錄，將所需子目錄複製至該處，只在新副本操作；不可重用原實驗輸出位置，也不可修改歸檔或原件。
2. 先閱讀該批原 README、來源及環境命令；手動確認所有建置、資料、輸出與專案絕對路徑已指向正確來源／新暫存副本。依賴絕對 project 路徑的真 CDELS／原始 RNG 腳本須在新副本人工調整，不假設換機可直接跑。
3. 若需要原負向案例檔，僅在新暫存副本解碼 8 份 `.base64` 至各自原相對檔名，依 manifest 核對解碼後大小／SHA；不得在本歸檔解碼成新 JSON，也不要替截斷內容補尾或修復成合法 JSON。
4. 原型額外依賴僅可用 `pip --target <新暫存目錄>/pydeps` 安裝，並按原建置腳本從新暫存目錄取 headers／模組；不得安裝、升降級或修改專案 `.venv`、正式依賴或設定。
5. 確認新目錄中的建置與輸出位置後，才依各原 README 分批編譯／執行／稽核；原 audit 也只能在新副本對新輸出執行。保存新的環境、來源 SHA 與結果，不能覆寫本次歷史證據。測試 watchdog 不得帶入產品 timeout。

本次只做來源封存、只讀數字／SHA 核對與文件同步，沒有執行上述重跑流程。
