# 候選架構第一關：資料共用與 task 獨立性

日期：2026-10-24。這是暫存控制原型，不是正式算法、設定格式、IPC 契約或輸出格式。專案正式檔案、依賴及既有研究附件均不修改。

## 原型與證據

- `kernel.cpp`：共同 C++ MKP 控制核心、有型別且欄位不可修改的題目物件、task 私有 RNG／編碼／負載／最佳解／歷史。每輪只翻轉一件物品；這不是 CDELS，也不測算法品質。
- `reference.py`：獨立 Python 參考計算。每一步從編碼重新求和，不共用 C++ 的增量評估；逐欄且區分型別比對。
- `build.py`、`environment.json`：編譯與環境記錄。Python 3.12.3、g++ 13.3.0、C++17、`-O2 -g -Wall -Wextra -Werror -pthread`。pybind11 3.1.0 僅放在本目錄 `pydeps/`。
- `smoke.py`、`smoke_results.json`：先通過 16 組單程序輸入、272 筆快照與 24 個比對器負向控制，才進行並行測試。
- `experiment.py`：相同 Python 管理器、相同 C++ 核心與相同同步 Python 輸出器，對照多執行緒／多程序。
- `output-serial-check/`、`output-two-check/`、`output-four-check/`：原始完整輸出、派工前實際輸入紀錄及各組 `results.json`。同名輸出拒絕覆寫。
- `audit.py`、`audit_results.json`：不執行求解、重新讀取已確認保存的證據並核對結果；包含來源 SHA-256。

## 兩種配置

1. 多執行緒：獨立管理程序，加上一個 Python 求解執行程序。該程序建立一份 C++ Bank，長存的各執行緒引用同一份題目。C++ 搜尋時明確釋放 GIL，不呼叫 Python。
2. 多程序：相同管理程序，加上各自長存的 Python 求解程序。每個程序建立自己的 C++ Bank；題目沒有透過共享記憶體、fork 繼承或跨程序指標共用。

Python 管理程序不載入原生求解模組。每個 task 完成 C++ 最終驗證後才返回完整 Result；所在執行單元同步保存，再回報摘要及位置，才接受下一題。不採背景 writer，也不把完整歷史送到管理程序。

為核對全部 bytes，獨立「測試檢查器」在收到正常保存確認後讀取已知輸出。這不是正式實驗管理重新評估結果，也不是通知遺失後的檔案補登。

## 案例及結果範圍

兩個測試題分別有 4／5 件物品、2 維容量；完整數值見 `reference.py`。seeds 1–4；更新 0／32 輪；初始全零、初始化不算更新。每輪只消耗一次 task 私有 MSVC 相容 RNG。紀錄初始化及每輪完整編碼、原始分數、可行性、負載、最佳解、RNG 狀態／次數及文字標籤。

每種配置分別使用 1、2、4 個執行單元，依序執行正序、反序與固定打亂順序；不同順序是不同測試批次，不是正式實驗允許重複 task 的新政策。

共 6 組配置、288 次正常求解及同步保存、4,896 筆快照。每個輸入在所有配置及順序下，完整保存 bytes 均與 Python 參考內容一致。這些數字不含前面的 16 次 smoke 原生呼叫。

| 執行單元 | 多執行緒的題庫／題目物件 | 多程序的題庫／題目物件 |
| --- | --- | --- |
| 1 | 1／2 | 1／2 |
| 2 | 1／2 | 2／4 |
| 4 | 1／2 | 4／8 |

這是核對物件持有與共用，不是 RAM 節省率或 RSS 量測。比較原生位址時同時使用 PID，不把不同程序的相同數值位址當成共用物件。

原型另刻意保留每個執行單元前題的 native Result，後續跨 seed、跨題目與批次後重新從舊 C++ 物件取值核對，最後釋放。退出前原型追蹤的結果物件與活動 task 數皆為 0；不據此宣稱整個程序無記憶體洩漏或 RSS 回到啟動值。

## 重疊執行如何驗證

C++ 在初始化後、32 輪的中點及完成後，經專用 Unix socket 到達測試協調點。所有參與者到達同階段後才放行，證明多個 task 已進入更新區段且尚未完成；多執行緒另核對不同 native TID 及同一 Bank 的同時活動數。

此同步只用來建立正確性證據，不是正式算法的熱路徑 API。包含同步等待的區段重疊不等於 CPU 指令同時執行、加速率或吞吐量。原型不以時間作排名。測試控制器的 30 秒安全等待上限只防止測試卡死，不新增正式 task 超時政策。

GIL 接線依據：[pybind11 官方文件](https://pybind11.readthedocs.io/en/stable/advanced/misc.html#global-interpreter-lock-gil)。明確釋放 GIL 後，純 C++ 工作才能由多個 Python 執行緒並行進入；此時不得任意使用 Python 物件。Result 由 Python 綁定持有原生所有權，轉換為 Python 資料只在返回、重新取得 GIL 後進行。

## 重跑：先複製來源到新的暫存目錄

以下使用專案既有 Python，但依賴及編譯輸出只寫新暫存目錄。不在原始證據目錄重新產生同名輸出。

```bash
gate1_replay_dir=$(mktemp -d /tmp/architecture-gate1-replay-XXXXXX)
cp /tmp/solver-architecture-gate1-vOJPeS/kernel.cpp /tmp/solver-architecture-gate1-vOJPeS/reference.py /tmp/solver-architecture-gate1-vOJPeS/build.py /tmp/solver-architecture-gate1-vOJPeS/smoke.py /tmp/solver-architecture-gate1-vOJPeS/experiment.py /tmp/solver-architecture-gate1-vOJPeS/audit.py /tmp/solver-architecture-gate1-vOJPeS/README.md "$gate1_replay_dir/"
/home/sean/optiforge-optimization-solver/.venv/bin/python -m pip install --target "$gate1_replay_dir/pydeps" --no-deps --disable-pip-version-check --no-cache-dir pybind11==3.1.0
cd "$gate1_replay_dir"
/home/sean/optiforge-optimization-solver/.venv/bin/python build.py
/home/sean/optiforge-optimization-solver/.venv/bin/python smoke.py
/home/sean/optiforge-optimization-solver/.venv/bin/python experiment.py --label replay-full
/home/sean/optiforge-optimization-solver/.venv/bin/python audit.py --suites output-replay-full
```

原始正式六組核對分三個小關卡執行：`--workers 1 --label serial-check`、`--workers 2 --label two-check`、`--workers 4 --label four-check`；每關通過後才進下一關。重跑耗時、PID、位址與檔案路徑不保證相同，語意結果 bytes 則逐輸入比對。

## 限制及停止點

- 尚未測試真實 CDELS、其他題型、大型題目、浮點重現性、跨平台或算法品質。
- 題目 const 介面與內容不變核對，不等於已驗證作業系統唯讀保護。
- 尚未做算法錯誤、原生崩潰、寫檔失敗、通知遺失或正式監督／恢復驗收；這些屬下一關。
- 未做速度、RSS／PSS、峰值或大結果壓力比較；全歷史 RAM 風險沒有解決。
- Python 輸出器只是本關的控制變因，不替正式保存語言或執行架構定案。
- 暫存目錄可能被環境清理；本輪不將資料移入專案，也不自動刪除任何證據。

完成本關核對後停止，先回報證據，再討論下一關；不自動進行故障注入或效能比較。
