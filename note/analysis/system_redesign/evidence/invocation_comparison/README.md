# 呼叫方式對照：研究證據與暫存重跑

實驗日期：2026-10-21。這是設計選型的研究附件，不是正式求解器、派工器或輸出格式。解讀方式見 [17 呼叫對照實驗](../../17_invocation_comparison_experiment.md)。

## 保存了什麼

| 檔案 | 用途 |
| --- | --- |
| [probe.cpp](probe.cpp) | 同一段合成 C++ 數值計算，以及擴充模組／獨立程序兩種測試接線。 |
| [build_probe.py](build_probe.py) | 在原型所在目錄建置執行檔與 Python 擴充模組。 |
| [experiment.py](experiment.py) | 小資料參考核對、大結果計量、故障注入與八 worker 對照。 |
| [experiment_results.json](experiment_results.json) | 當次原始結構化結果，包括 45 次單 worker 計量、9 個並行批次及故障測試摘要。 |

三份來源檔與當次暫存來源逐 bytes 相同。JSON 的內容與數字未改，文字歸檔時僅補檔尾換行；原始絕對路徑、PID、traceback 與時間值照原樣保留，不代表那些暫存路徑目前或將來仍存在。

不納入編譯產物、`pydeps`、Python cache 或約 10.526 GiB 的測試二進位輸出。這不是完整磁碟快照；原始 JSON 保留測量與核對結果，不保存每份大型輸出的內容。重跑可重新產生資料，但不保證重現相同耗時、PID 或記憶體抽樣值。

來源 SHA-256：

| 檔案 | SHA-256 |
| --- | --- |
| probe.cpp | d42e990688446becda1bb874bd75227a482e58980215a3991aea1fbb47448c08 |
| build_probe.py | 95ba1a455fe6008c5f84b2ef0d84f93ff024bc7912ab01ba435ef943981b3011 |
| experiment.py | 8e0e51d3d5786cacf498bec3b9267044aabc339a340d5fd44d79c93701a22f5a |

雜湊僅供這份研究附件核對，不新增正式系統的版本或 digest 契約。

## 當次環境

- Linux／WSL 工作區，Python 3.12.3、g++ 13.3.0，系統可見 12 個 CPU。
- 測試接線使用 pybind11 **3.1.0**，只安裝於原型暫存目錄。這不是正式專案依賴版本的定案。
- 共同建置旗標：`-std=c++17 -O2 -Wall -Wextra -pthread`；擴充模組另加 `-DBUILD_BINDING -shared -fPIC -fvisibility=hidden`。
- Python 開發標頭須與執行 Python 相符；當次為 `/usr/include/python3.12`。
- 原型另使用 Linux 的 `memfd_create`、記憶體映射、Unix socket／檔案描述元交接與 `/proc/*/smaps_rollup`，不能當成原生 Windows 可執行範例。
- 不需要將 pybind11 安裝進專案虛擬環境；建置程式直接讀暫存 `pydeps` 內的標頭。

## 必須複製到暫存目錄後執行

**不要在本研究附件目錄直接執行或 import 原型。**`experiment.py` 載入時會建立 `results/`；建置、JSON 與大型結果也都寫到原型所在目錄。保留原始程式是為了追查，不表示它已改成正式工具。

以下從專案根目錄操作，使用獨立暫存目錄；不變更專案依賴、註冊或求解流程：

```bash
invocation_repo_root="$PWD"
invocation_python="$invocation_repo_root/.venv/bin/python"
invocation_probe_dir=$(mktemp -d /tmp/cpp-invocation-replay-XXXXXX)
cp "$invocation_repo_root/note/analysis/system_redesign/evidence/invocation_comparison/probe.cpp" "$invocation_probe_dir/"
cp "$invocation_repo_root/note/analysis/system_redesign/evidence/invocation_comparison/build_probe.py" "$invocation_probe_dir/"
cp "$invocation_repo_root/note/analysis/system_redesign/evidence/invocation_comparison/experiment.py" "$invocation_probe_dir/"
"$invocation_python" -m pip install --target "$invocation_probe_dir/pydeps" --no-deps pybind11==3.1.0
"$invocation_python" "$invocation_probe_dir/build_probe.py"
"$invocation_python" "$invocation_probe_dir/experiment.py" correctness
```

先檢查三種配置的 `passed` 皆為 true，再考慮手動執行下列較大測試。不要複製已封存的 JSON 到新目錄充當新結果；新原型會依完成階段建立自己的 JSON。

```bash
# 會寫入大量測試資料並呼叫 fsync；全套約產生 10.5 GiB 二進位輸出。
"$invocation_python" "$invocation_probe_dir/experiment.py" benchmarks
"$invocation_python" "$invocation_probe_dir/experiment.py" faults
"$invocation_python" "$invocation_probe_dir/experiment.py" parallel
"$invocation_python" "$invocation_probe_dir/experiment.py" summary
```

這些是手動重跑說明，**本次文件整理未執行上述建置或實驗**。不要在仍有測試程序使用暫存目錄時清除它；本說明不自動刪除輸出。

## 閱讀原始 JSON

- `correctness`：每種配置記錄 9 個檢查通過；保留前題結果再求解下一題的檢查另見來源程式，未另設 JSON 計數。
- `benchmarks`：每種尺寸／配置五筆，暖機不列入這 45 筆。包含階段耗時、PSS 抽樣、完整輸出 SHA-256、RNG、校驗值與摘要訊息大小。
- `parallel`：每種配置三批，每批 8 worker、每題 64 MiB；總時間不是逐題時間的加總。
- `faults`：每種配置一組八 worker 測試；含失敗工作實際輸入與已知終止事實。健康工作的完整逐題紀錄不是逐筆收錄於此陣列；通過條件見來源中的斷言。
- `environment`：測試當時的環境與保存口徑；不是正式系統的設定檔。

原型控制端使用執行緒等待與取樣，輸出仍由各 Python worker **同步**執行；這不是新增背景 writer。共享記憶體尺寸、固定二進位協議與來源中的欄位名稱都不是正式契約。
