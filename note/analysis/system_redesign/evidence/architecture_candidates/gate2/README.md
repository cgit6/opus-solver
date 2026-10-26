# 候選架構第二關：故障處理控制原型

日期：2026-10-24。所有來源、依賴、編譯產物、故障輸出及報告都只在此暫存目錄。第一關原始目錄與正式專案不修改。本關不做效能排名，也不替正式架構定案。

## 範圍與檔案

- `kernel.cpp`：第一關 C++ 控制核心的獨立副本，新增原生更新中點的 `std::runtime_error`／`SIGABRT` 測試開關；未啟用時保留原計算。模組仍名為 `gate1_kernel`，只是沿用綁定名稱。
- `reference.py`、`smoke.py`：獨立 Python 參考核對。加入開關後重新通過 16 組正常輸入、272 筆快照、24 個比對器負向控制。
- `fault_workers.py`：兩種拓撲共用的執行／同步保存程式，記錄真實保存錯誤的動作、路徑、類型、errno、訊息及 traceback 字串；不保留例外物件使 Result 意外延壽。
- `controller.py`：獨立管理程序，以輸入紀錄、通知及程序退出事件判定。它不讀取結果文件、不自動重跑，也不把歷史送回主程序。
- `scenarios.py`：逐項故障測試及獨立讀檔檢查器；所有輸入先保留，先保存一筆正常結果，才讓目標與其他 task 進入原生更新區段並注入故障。
- `audit_faults.py`：不執行求解，重新核對各情境輸入、派工紀錄、原始事件、最終狀態及已保存完整 bytes；另檢查控制器沒有讀取／掃描結果檔案的程式。
- `output-*/`：各小關卡及重複批次的原始證據，每個情境都有 `planned_inputs.json`、`assignments.jsonl`、`events.jsonl`、`controller_report.json`、`observer_results.json` 與實際輸出。
- `audit-*.json`：獨立核對結果及來源 SHA-256；實際通過輪數以報告為準，不用沒有執行的計畫次數冒充結果。

## 六個具體情境

| 情境 | 注入方法／核對行為 |
| --- | --- |
| C++ 可捕捉算法錯誤 | 其他 task 都已到達更新中點後，目標在 C++ 實際 throw。收到完整算法錯誤後停止所有求解程序，不再派新題。 |
| 原生致命退出 | 同樣在原生更新中點實際 `SIGABRT`。管理程序保持存活，記實際退出訊號、未確認輸入與最後通知，不聲稱知道是哪段算法根因。 |
| 軟體路徑錯誤 | 以普通檔案占用輸出目錄位置，真正觸發 `FileExistsError`／`NotADirectoryError`。記原因後釋放 Result、核對清理，原執行單元接一個新 task，並確認其他 task 不被取消。 |
| 序列化錯誤 | 將不能表示為 JSON 的 set 交給真正的 JSON 序列化器，觸發 `TypeError`。與路徑錯誤走相同清理及重用檢查，不自動重試失敗題。 |
| 檔案完成但沒有最終通知 | 結果完整保存、flush／fsync／close 後，host 直接退出，不送 saved。控制器維持交付未確認；外部測試檢查器讀到完整檔案，也不回頭補登成功。 |
| 通知已送出但先觀察到退出 | saved 通知送出後 host 直接退出；測試控制器刻意先等待退出，再處理已交付通知。結果仍維持已交付，不因程序退出被撤銷。 |

每種情境對照多執行緒／多程序，以及 2／4 個執行單元，共 24 種組合。先逐小關卡跑完首輪並獨立核對，再做重複批次；原始證據各自保存，不覆寫前輪。

## 本輪實際結果

24 種組合各執行 3 輪，72 個情境全部通過；詳細見 [最終獨立核對](audit-final-72.json)。先前 `audit-first-24.json`、`audit-repeated-48.json`、`audit-all-72.json` 保留各階段當時的來源摘要及核對結果；本文件補入總結後另產生最終核對，不覆寫它們。

- 312 次實際派工，起始數值及派工前輸入紀錄均重新核對，無自動重跑。
- 156 筆確認交付、12 筆已知算法例外、24 筆保存錯誤、120 筆交付未確認；另有 120 筆計畫內任務未派出。這是測試案例計數，不是正式統計成功率定義。
- 168 份完整文件／5,544 筆快照與獨立參考內容逐 bytes 一致。其中 12 份是刻意遺失最終通知的完整文件，控制器仍維持交付未確認，沒有補登。
- 24 次保存錯誤後清理成功，再由相同 PID／native TID 求解新題；其結果與其他 task 的結果均符合參考。
- 原型建立的 144 個求解程序都已退出，沒有自動重跑失敗題；不表示強制終止時有執行算法清理。

這些結果不包含下文列出的清理失敗／不可信分支，也不代表正式系統的全部錯誤政策已通過。

## 終止與歸因界線

原型只終止其自行建立的求解子程序，子程序關閉 core dump，不會對其他專案程序或整個系統送訊號。控制器在收到明確算法錯誤或觀察到執行 host 意外退出後，停止本次原型的所有求解 host；不等待算法安全點，不承諾被終止程序執行 finally／C++ 清理。

原生 SIGABRT 是測試注入的已知方法，但管理紀錄只採實際可觀察的訊號與最後通知；未確認 task 的算法根因仍為 `not_determined`。對非算法原因的任意程序退出，正式系統分類尚未定案；本原型因失去執行 host 而停止，是測試安全處置，不代替該決策。

控制端以 [Python 3.12 官方 multiprocessing 文件](https://docs.python.org/3.12/library/multiprocessing.html#multiprocessing.Process.terminate) 核對 sentinel、exitcode 與 terminate／kill 行為。被強制終止的程序及其 IPC 不重用，不把 `future.cancel()` 當成終止正在運行的算法。本輪沒有在半段訊息傳送中終止，不能宣稱已驗收任意 IPC 截斷或損壞。

測試協調點、20 秒看門狗及終止後的等待只是防止測試自身卡死，不新增正式單 task 超時或暫停／續算功能。

## 清理成功如何確認

Python 輸出器已離開失敗呼叫並只留下可序列化錯誤資訊。原生 Result 的 Python 所有者以 weakref 確認已釋放，C++ 題目內容仍一致；隨後同一 PID、同一 native TID 執行新 task，其全部保存內容與獨立參考相同。其他 task 刻意仍停在原生協調點，之後正常完成，用來確認沒有因保存錯誤被一併取消。

這只驗證本次原型的「清理成功」分支，不是通用健康檢查，也不保證任何任意 C++ 錯誤後都可重用。

**尚未決定／未驗證：清理失敗或狀態不可信時，多執行緒案應只停用一條執行緒，還是替換整個共用程序，以及如何處理其中其他正常 task。**原型不擅自採用其中一種。遇到不可信清理時不接受新 task；本輪沒有注入此分支，不宣稱 D40 完整驗收。

## 重跑

先將本目錄來源複製到新的暫存目錄；不要在原始證據目錄用相同 label 重跑。依賴 pybind11 3.1.0 只安裝到新目錄 `pydeps/`，不安裝進正式專案環境。

```bash
gate2_replay_dir=$(mktemp -d /tmp/architecture-gate2-replay-XXXXXX)
cp /tmp/solver-architecture-gate2-wE6cmX/kernel.cpp /tmp/solver-architecture-gate2-wE6cmX/reference.py /tmp/solver-architecture-gate2-wE6cmX/build.py /tmp/solver-architecture-gate2-wE6cmX/smoke.py /tmp/solver-architecture-gate2-wE6cmX/fault_workers.py /tmp/solver-architecture-gate2-wE6cmX/controller.py /tmp/solver-architecture-gate2-wE6cmX/scenarios.py /tmp/solver-architecture-gate2-wE6cmX/audit_faults.py /tmp/solver-architecture-gate2-wE6cmX/README.md "$gate2_replay_dir/"
/home/sean/optiforge-optimization-solver/.venv/bin/python -m pip install --target "$gate2_replay_dir/pydeps" --no-deps --disable-pip-version-check --no-cache-dir pybind11==3.1.0
cd "$gate2_replay_dir"
/home/sean/optiforge-optimization-solver/.venv/bin/python build.py
/home/sean/optiforge-optimization-solver/.venv/bin/python smoke.py
# 會刻意讓自己建立的子程序 throw／SIGABRT／退出；主控程序保持運行。
/home/sean/optiforge-optimization-solver/.venv/bin/python scenarios.py --label replay-one
/home/sean/optiforge-optimization-solver/.venv/bin/python audit_faults.py --label replay-one --expected-rounds 1
```

首輪使用 caught-two／abort-two／save-two／delivery-two／native-four／save-four／delivery-four 七個 label 分段執行。若要追加完整重複輪，使用新的 label；核對時 `--expected-rounds` 應等於已完整執行的輪數。

## 不包含

本關不是正式 supervisor／IPC／故障恢復驗收，不測真實 CDELS、任意時間點退出、半段文件／訊息、卡住算法、最終不可行解、多種真實算法交互作用、任意第三方庫、硬體／資源故障、效能或大歷史記憶體風險。`control-A/B` 只是不同任務標籤，仍使用同一個小型控制計算核心。

本輪完成後停止，先回報證據與清理失敗分支的設計缺口，不自動進入正式改造或效能比較。暫存目錄可能被環境清理；本次不移入專案，不刪除任何證據。
