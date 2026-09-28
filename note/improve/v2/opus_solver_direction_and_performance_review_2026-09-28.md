# opus-solver：方向、替代方案與效能競爭力評估

研究日期：2026-09-28  
專案快照：`cgit6/opus-solver@8557dd02e2161513d34334413e00908ddd1ac224`  
評估性質：官方文件／原始碼調查、現有程式靜態分析、決策與基準測試設計。**沒有執行跨框架效能測試，沒有實測速度排名。**

## 先看結論

**「離散、連續、AI 模型最佳化都能做，而且高效能」不是尚未有人做的方向，也不足以單獨構成新框架的差異化。**問題表示、算法執行、GPU／叢集運算、實驗管理及研究分析，都已有相應工具；其中 Benchopt、jMetalPy 的實驗功能比單純算法庫更接近你的用途，不能只拿你的系統跟 Optuna 的調參 API 比較。[S01–S14]

**但功能重疊不等於你的全部成果沒有價值。**自有 solver、問題資料、驗證規則、實驗配方、適配程式都可以保留；需要重新論證的是「為何還要自行維護通用執行核心」，不是「既有成果是否全部作廢」。這是本評估的決策建議，而非已證明的市場需求。

目前不建議把 v2 直接擴張成三領域的全新高效能平台。我建議先驗證一個較窄的假說：

> 在你實際使用的單機、多核心、Python／Numba 求解器研究流程中，自建部分能否在相同正確性與保存要求下，顯著降低完成實驗的時間、記憶體或新增實驗的工作量？

若第三方框架加一層薄適配就做得到，應整合而不是重建；若實測發現重要且難以用薄適配補上的缺口，再只自建該缺口。**目前的證據足以否定「功能範圍本身是獨特性」，但不足以判定你的 runner 一定比別人慢或完全沒有保留價值。**

---

## 1. 先分開你可能在比較的三種系統

| 層次 | 要解決的問題 | 主要對照 | 與你的關係 |
|---|---|---|---|
| 求解與候選解評估 | 下一個候選解怎麼產生，怎麼算 fitness，怎麼演化？ | pymoo、Nevergrad、pagmo／pygmo、EvoTorch、EvoX | 可當 solver／計算後端，不必全部視為整套系統替代品 |
| 實驗與資源執行 | 多組設定如何跑，怎麼分配 CPU／GPU，如何處理中斷？ | Benchopt、Ray Tune、joblib；Optuna 含 study／trial 管理 | 最需要驗證能否取代你自行維護的 runner |
| 研究證據與比較 | 如何保存實驗、重複測量、追蹤品質曲線和統計分析？ | Benchopt、IOHprofiler、jMetalPy 的實驗工具 | 與你想建立的研究工作流程直接重疊 |

這是用途分類，不是互斥分類。例如 Benchopt 同時涉及第二與第三層。官方文件支持上述功能分工，但不代表本次已逐一部署或測試。[S01–S14]

因此，不能由「Optuna 不內建你的 BSMA」推出「你的整套平台有必要存在」；也不能由「pymoo 支援 MKP 的表示方式」推出「它已經滿足你所有成果保存與恢復規則」。應比較一條完整工作流程，而不是比功能標籤。

## 2. 目前已存在什麼？

以下是有代表性的對照，不是 GitHub 所有專案的完整數量調查。沒有用 stars 或貢獻者數替代成熟度、效能或適配性判斷。

| 專案 | 本次確認的能力 | 對你方向的實際意義 | 仍須避免的誤解 |
|---|---|---|---|
| **Benchopt** | datasets／solvers／objectives 組合、參數網格、重複次數、seed、結果快取與發布；可用本機 joblib 或叢集後端。[S01–S04] | **最值得優先做遷移概念驗證的研究流程對照。**它不只是替你挑參數。 | 快取命中不等於 task 內精確 checkpoint；仍須核對你的停止、失敗與發布語意。 |
| **jMetalPy** | Experiment／Job 批次實驗、多次 run、workers、指標彙整、CSV 及統計分析入口。[S05] | 你目前「算法 × 題目 × 重複實驗 × 統計」不是罕見架構。 | 它的算法／problem 介面和研究指標未必直接符合你的所有自有 solver。 |
| **IOHprofiler** | 離散 PBO、連續 BBOB、實驗記錄、固定預算／固定目標分析與統計視覺化。[S06] | 「跨離散與連續的研究基準與證據層」也已有既有生態。 | 基準問題和資料分析能力，不代表可直接管理所有 GPU 訓練生命週期。 |
| **pymoo** | 連續、binary、discrete、permutation、mixed／custom variables；平行評估；算法物件序列化 checkpoint。[S07–S09] | 通用問題介面、TSP 類表示與可擴充算法不是新差異。 | 官方 checkpoint 範例不是你所有外部狀態都可恢復的通用保證。 |
| **Nevergrad** | 連續／離散／混合參數；以 learning rate、batch size、architecture 作示例；ask／tell 與 executor 平行評估。[S10–S11] | 直接反證「離散＋連續＋AI 調參」是未被覆蓋的組合。 | 有離散參數不代表內建最適合所有 TSP／CVRP 的操作子；需要選擇或適配。 |
| **pagmo／pygmo** | C++ 底層、連續與整數問題、約束／多目標、非同步 island model。[S12] | 「平行、高效能、通用優化」早已有專門系統。 | island 間遷移會改變搜尋過程，不能冒充同算法獨立 repeat 的 scheduler 對照。 |
| **Optuna** | 可嵌入任意目標計算；多執行緒、多程序、跨節點 study／trial 執行與儲存。[S13] | AI 超參數最佳化已有直接替代工具。 | 搜尋策略、trial 狀態庫與完整通用 GPU 資源調度器不是同一件事。 |
| **Ray Tune** | 平行 trial 執行、資源配置、狀態追蹤、停止／失敗策略、恢復與使用者定義 checkpoint。[S14–S16] | 現有 solver 可以被包成 trial，未必需要改成 Ray 的內建算法。 | 自動調參不是你固定參數組比較的必要條件；要關掉不相干的 pruning／搜尋差異再比。 |
| **EvoTorch** | PyTorch 演化計算、GPU 搜尋與 fitness、Ray actors／叢集、監督式 neuroevolution 與 RL 用例。[S17–S18] | 連「演化算法＋AI 模型＋高效能計算」也不是空白。 | 任意物件可表示，不代表所有離散表示都自動向量化或享有相同 GPU 加速。 |
| **EvoX／EvoXBench** | EvoX 提供 GPU／分散式演化計算與 neuroevolution；EvoXBench 把神經架構搜尋轉成多目標基準。[S19–S21] | 要以 AI 演化或 NAS 為新價值，必須對照此類更直接的系統。 | 生態套件的能力不能全部算作單一核心包；NAS 基準評估不等於真實訓練成本。 |

### 成熟度該怎麼看？

貢獻者更多，只是可能有較多維護資源，**邏輯上推不出特定工作負載一定更快、你的功能一定更穩定**。採用時應實際核對版本與依賴相容性、你會使用路徑的測試、文件與錯誤處理、維護反應、授權及遷移負擔。這些是採用評估維度，不是本次已完成的逐專案成熟度評分。

## 3. 「AI 模型最佳化」必須拆開

它不是與離散、連續互斥的第三種數學問題，而是應用領域。你選擇哪一種 AI 工作，會改變真正需要的執行能力。

**超參數調整。**例如 learning rate、batch size、正則化、模型選型，通常能表示成連續、整數與類別參數。Nevergrad／Optuna／Ray Tune 已涵蓋相應介面；這條路很難僅憑增加 `problem_type=ai` 形成差異。[S10、S13–S15]

**直接演化模型權重或策略。**問題變成大量候選模型的權重組裝、批次推論／環境互動、設備記憶體與張量計算。EvoTorch／EvoX 已在處理這一層；它與「一個 process 跑完一次完整求解」不是相同的加速問題。[S17–S20]

**神經架構搜尋。**EvoXBench 已提供把 NAS 表示成優化基準的路徑。若使用查表或 surrogate，吞吐量不能當成實際訓練神經網路的吞吐量。[S21]

**建議：**先把三領域視為未來可相容的方向，而不是現在全部實作的任務。以一個具體 AI 工作負載驗證資料與執行介面，遠比先建立「支援全部 AI」的抽象更有判斷力。

## 4. 你目前的架構，哪些是可用資產？

在已確認的專案快照中：

- `RunTask` 已是獨立求解任務；`MachinePool` 使用 `ProcessPoolExecutor`，任務交給 worker 執行。[R02]
- `ProblemBank` 及 worker view 已處理題目資料的 shared-memory 接線。[R03]
- `MachinePoolSession` 已提供重用 worker pool 的路徑；不是完全沒有 persistent pool。[R02]
- `BSMA_numba.py` 把主要迴圈放在 Numba 編譯函式內，並保存程序內的前處理快取。[R04]

**我的判斷：這是一個有合理效能設計基礎的本機研究 runner，不是一個已證明優於現有框架的通用高效能引擎。**

可重用的核心資產包括你的 solver、問題資料模型、驗證、特定實驗設定及數值計算實作。換實驗 runner 不代表要改掉算法；可以先用 wrapper 呼叫完全相同的 solver。是否真能低成本接入，應用小原型驗證。

### shared memory 和 Numba 不是獨有能力

Ray 的同節點 NumPy 物件可透過 object store 做零複製讀取；joblib 可透過 memmap 分享大型陣列，並提供 worker pool 重用、批次派工與內部執行緒限制。[S22–S23]

因此，競爭點不是「有沒有共享記憶體」，而是：你的負載中共享了哪些資料、避免多少複製、付出多少同步／初始化成本，最後是否在相同保障下比較便宜。即使你的手工 SHM 路徑有更好表現，也可能只需要保留一個專用資料適配器，而不是整套自建 scheduler。

## 5. 靜態分析找到的效能問題與未驗證假說

以下刻意分開「直接可見的程式事實」與「需要量測才知道影響程度」。

### 5.1 直接問題：提早停止後，evaluation_count 仍按最大迭代數計算

`_bsma_main_loop_numba` 有：

```python
if gbest_fit == glbal_best:
    break
```

但 `BSMANumbaSolver.solve` 回填：

```python
evaluation_count = int(pop_size + max_iterations * pop_size)
```

迴圈沒有把實際完成迭代數回傳給外層。**因此在提早停止路徑，回填的計數仍是最大工作量，而不是實際工作量。**這是基於原始碼的條件性結論，本次沒有跑測試觸發。[R04]

影響：不能直接用此欄位除以 runtime，宣稱實際 evaluations/s；也不能把「有 max_iterations 上限」當作「每次都做完全相同工作量」。比較固定工作量時要確認實際迭代／評估數；比較達標時間時則另設固定目標實驗。

### 5.2 直接事實：SolveResult.runtime 不是完整系統時間

`BSMANumbaSolver.solve` 的計時包住 core 初始化與 `core.run()`，不涵蓋整個主程序的題庫組裝、worker 啟動、排程、最後驗證與輸出。`linprog_runtime` 發生在已被包住的 core 初始化內，不能再無條件加一次，否則可能重複計時。[R04–R05]

影響：現有 runtime 可以作局部診斷，**不能直接當作 framework 端到端效能**。應另量從收到實驗設定到完成所需持久輸出的 wall time，並把冷啟動與暖執行分開。

### 5.3 可見風險：一次建立並提交全部 futures

`MachinePool` 的平行路徑先建 tasks 清單，再用 comprehension 為所有 tasks 呼叫 `pool.submit`；結果先留在字典，之後才組裝和驗證。提交窗口沒有在這條路徑中限制為與 worker 數成比例。[R02]

推論：任務很多而每個任務很短時，Python 物件、IPC、排隊 futures 和結果累積可能成為負擔。但這不是已量出的瓶頸；需要量測 pending 數、主程序記憶體、完成尾段時間。joblib 本身已有 `pre_dispatch` 和自動 batch 等能力，可作較強的對照，不應只比較未調校的範例程式。[S23]

### 5.4 可見風險：驗證集中於結果收齊之後

平行路徑的 `problem.validate(solve_result)` 在 `_build_machine_results` 中由主程序逐筆執行。[R02]

推論：若驗證只是短小檢查，代價可能可忽略；若它重新執行昂貴 fitness，可能形成明顯串行尾段。因此應分別量測 solve 與 validate，而不是為了速度直接取消驗證。未來 AI 模型評估也必須先定義驗證是否重跑訓練或只是檢查記錄。

### 5.5 可見風險：共享原始題目不等於共享所有前處理

`BSMANumbaCore._cp_list_cache` 是類別層級字典。在多程序模型下，它是每個程序自己的快取；`_cp_list_cache_key` 每次把 values、weights、capacities 轉成 bytes。快取 key 也持有資料 bytes。[R04]

推論：同題目的前處理仍可能在多個 worker 重複；大量不同題目會有快取記憶體與建 key 成本。是否值得把確定不依 solver 狀態的前處理共享，需要量測。若把前處理移到求解計時之外，仍須在端到端指標呈現它，不能把成本搬走就宣稱消失。

### 5.6 尚未證明的能力：三領域與 GPU／叢集競爭力

目前選讀的 BSMA Numba 路徑直接依賴 MKP 的 values、weights、capacities 及 best_known；外層 MachinePool 是本機 process pool。[R02、R04]

這支持「目前 MKP 批次研究可以有專門化效率」，不支持「同樣結構搬到連續問題與 AI GPU 工作就維持優勢」。尤其是 GPU 批次評估與內部向量化，需要在相應層級測試。[S17–S20]

### 執行基線限制

本次核對到 master 仍是上列 commit。該快照的 `engine/builders.py` 與根 `__init__.py` 匯入 `BSMA`、`BSCA` 等模組，但 Git tree 的 `solver/` 目錄沒有相應檔案；Numba 路徑也匯入 `.BSMA`。這是乾淨 checkout 基線的阻擋風險，而不是本次已執行安裝所得的錯誤紀錄。[R06]

正式實測應先使用完整、可重現、可啟動的 commit。舊文件中的 pytest 通過數，不等於這個 commit 已由本次重新驗收，更不等於跨框架效能證據。

## 6. 為什麼原參考系統的高併發不能直接證明你的效能？

本次沒有取得並獨立測試那套原參考系統，因此不假設它是 I/O-bound，也不對其效率下判斷。能確定的是，**設計概念的移植與效能證據的移植是兩件事**。

必須區分四件事：

| 指標／層級 | 真正代表什麼 | 可能的誤判 |
|---|---|---|
| 同時在跑的 task 數 | concurrency | 多開程序，卻因搶 CPU、RAM 或 GPU 更慢 |
| 完整實驗吞吐 | 每秒多少符合要求的獨立任務真正完成並保存 | 不保存、不驗證的版本看起來比較快 |
| 單次求解計算速度 | 相同算法和工作量執行多久 | 把 Numba kernel 的優勢歸給排程器 |
| 解的品質／達標效率 | 相同預算下取得什麼品質，或達標花多久 | 換更強算法後宣稱 framework 比較快 |

CPU 任務還要考慮 worker 裡的 BLAS／OpenMP 執行緒；joblib 文件明列了多程序內部 thread-pool oversubscription 的風險。很短的工作也會被派工成本吞噬，Ray 官方提供了對應反模式說明。[S23–S24]

一個純示意的計算：若排程及協調只佔總時間 5%，即使把它完全消除，總時間也最多少 5%，速度約提高到 `1 / 0.95 = 1.053` 倍。**5% 不是你的實測值。**這個例子只是說明，若主要時間花在算法或模型訓練，重寫外層 runner 未必是最大的槓桿。

## 7. 哪種價值假說比較值得驗證？

### A. 專屬研究整合層：目前最合理的起點

候選定位：研究者保留既有 Python／Numba solver 與題庫，少量接線就能完成固定實驗矩陣、可追蹤種子、驗證、逐任務保存、恢復與一致格式輸出。

它不宣稱這些功能全球首次出現，而是檢驗：**對你的研究流程，是否比自行拼裝既有工具更省事、更可靠？**首先要對照 Benchopt 和現成 runner；若少量 adapter 就能做到，保留薄整合層就是成果，不需要把它包裝成全新底層平台。

### B. 高密度單機 CPU／Numba runner：可能，但效能必須實證

候選工作負載：大量獨立、固定參數的求解，題目資料與某些確定性前處理可重用，研究者不需要長駐叢集服務。

可能的差異不是「有 multiprocessing」，而是完整可靠工作流程下的低啟動成本、低記憶體、控制小任務開銷與低接入負擔。每一點都要與 joblib、Benchopt 的合理配置比較。若只比厚重叢集預設值更快，不足以證明值得維護自建核心。

### C. 強恢復／精確重現平台：必須由需求推動

算法內部 checkpoint、完整 RNG state、失敗後的正式成果保護，可能有工程價值。但 pymoo 與 Ray 已有各自的 checkpoint 路徑，不能把 checkpoint 本身當成獨創功能。[S09、S16]

若只需要「已完成 task 不重算」，不要先把所有 solver 改成 managed RNG。更嚴格的可恢復狀態，只有在真實使用者願意為它承擔適配成本、而現有工具無法滿足時，才值得投入。這是方案選擇，不是擅自刪除已確認需求。

### D. 全面 GPU／多節點／三領域平台：目前不建議作主線

在這條路上，要同時處理張量資料流、設備資源、算法介面、模型適配、執行可靠性與研究輸出；現有 EvoTorch／EvoX／Ray 生態已有對應能力。[S14–S20]

不能保證沒有機會，但目前沒有你的效能量測、外部使用者需求或難以適配的代表案例，足以支持這麼大的投入。更好的進入方式是先與它們整合，從具體缺口切入。

## 8. 一個能決定「自建／整合」的比較實驗

以下是建議的實驗方案，**不是已完成的測試結果**。

### 8.1 第一輪只選三個實作，不先重建 v2

1. 你的完整可運行 commit，使用現行主要 batch 路徑。
2. **相同 solver callable＋合理配置的 joblib**，必要時使用唯讀 memmap、適當的 batch 和內部執行緒限制。
3. **相同 solver＋Benchopt 最小 adapter**，使用一次求解模式或單次固定預算條件，對齊觀測與驗證需求。

選這三者的原因：第一個是現況，第二個辨認自建排程是否有優勢，第三個檢驗完整研究流程是否已可用既有工具取代。它們不是全面市場排名。

若這一輪已支持整合，就不必先造一套更大的 scheduler。確定有 GPU／跨節點需求時，再加入 Ray；確定是 neuroevolution 時，再對照 EvoTorch／EvoX 的計算路徑。

### 8.2 小心 Benchopt 預設會多做工作

Benchopt 的 iteration／tolerance 曲線模式可能用不同預算多次從頭求解；callback 模式可以單次執行追蹤曲線，run_once 與 SingleRunCriterion 則提供一次執行的方式。[S04]

因此，不能把「你的 solver 跑一次」和「對方建立多點收斂曲線」的總時間直接比較。首先對齊實際求解次數、總評估數、記錄頻率和最終輸出，再談額外開銷。固定參數組比較也不應混入自動 pruning 或自適應選點帶來的差異。

### 8.3 最小 workload 集

| workload | 用來回答什麼 | 首輪選擇 |
|---|---|---|
| 真實 MKP＋既有 Numba solver | 目前最重要的工作是否真的受益？ | 必做；小、中、大實例及多個參數組 |
| 校準過的短 CPU 任務 | 任務粒度小時，提交／傳輸／保存何時成為瓶頸？ | 診斷用；不可單靠它下整體結論 |
| 大型唯讀題目資料、多 repeat | SHM 與資料重用能降低多少 RAM／載入成本？ | 必做；控制資料一致與輸入副本 |
| 一個真正的連續問題 | 泛化之後是否仍能正確接入和計量？ | 第二輪；不先建立完整題庫 |
| 一個明確 AI 任務 | GPU 調參或權重演化的實際資源瓶頸在哪？ | 第二輪，二選一；不混稱 AI 全支援 |

短任務可設定不同工作量檔位，但應使用計算 kernel 而不是只用 sleep 代表 CPU 運算。No-op／sleep 測試最多用於隔離排程延遲，不能代表你的真實算法。

### 8.4 公平比較的控制條件

同一機器、同一資料內容、同一 solver kernel、同一工作量與停止策略、相同版本、相同資源上限。固定初始 seed 或輸入；比較算法本身不同的實作時，另設品質／預算實驗，不歸入 runner 排名。

分開記錄：全新程序／冷 JIT、已有編譯快取、持續 worker／暖資料三種條件。不能讓自己的快取已熱而競品包含安裝、下載或首次編譯。

CPU worker 梯度以可用實體核心或實際 CPU quota 為界；固定內部 BLAS／Numba／框架執行緒。GPU 測量需在適當同步點計時，並記錄裝置、VRAM 與批次設定。

記錄所有必要輸出與可靠性要求。只在記憶體中留結果的 baseline 可以測「裸排程成本」，但不能用來宣稱比具備耐久保存的方案更有產品競爭力。

將測試順序隨機交錯，重複執行並報告中位數與分布；不只貼最好的那一次。樣本數和資源上限應依實際運行變異與成本決定，不能把任意小樣本當作穩定效能結論。

### 8.5 指標

**主要指標：**從開始到所有要求的有效結果可被持久讀取的 wall time；或 `有效且已提交的唯一 task 數 / wall time`。

**診斷指標：**worker 啟動／JIT／載入／前處理／solve／validate／保存／輸出時間、主程序 pending futures、CPU 利用、GPU 利用、峰值記憶體和尾段延遲。這些階段可能重疊，不能把各程序時間直接相加當 wall time。

**記憶體：**共享記憶體情境下，單純加總程序 RSS 容易重複計入共享頁；建議量測一致範圍的程序集合 PSS 或 cgroup 記憶體，並記錄 shared memory／page cache 的計入方式。GPU 另記 allocated／reserved VRAM。這些是測量設計，不是本次量測結果。

**可靠性：**完成任務在重啟後不重複計入、未提交任務可以明確重跑、設定改變被辨識、輸出失敗不破壞舊成果、沒有殘存計算被誤認為停止。允許重算不代表允許重複記帳。

**接入成本：**把同一個既有 solver 接到不同方案，記錄需要改多少算法內部位置、新增多少必要測試／設定，以及後續改一個參數或加一個問題的工作量。單純 adapter 行數不是充分指標。

### 8.6 決策規則

實驗前先訂「值得保留自建核心」的條件，避免看到任何微小優勢就繼續加功能。

一組**可討論而非行業標準**的門檻：在主要真實 workload、相同正確性與保存要求下，有穩定而具實際意義的時間或記憶體改善，例如 wall time 少 20% 或峰值記憶體少 30%；或者在效能近似時，日常接入與維護工作明顯減少。這些數字沒有被本次驗證，應依你能接受的維護成本調整。

| 結果 | 建議 |
|---|---|
| Benchopt＋薄 adapter 已滿足需求，效能差異不重要 | 將平台方向改為整合；保留 solver、problem、驗證和實驗配方 |
| joblib 已達相同效能，自己的特別價值是保存／驗證 | 用現成 executor，自建小型研究控制層 |
| 自建路徑在核心 workload 有足夠效能優勢 | 保留專用本機 backend，公開支持範圍與量測方法；不自動擴張成全域框架 |
| 只有缺少輸出／驗證的版本比較快 | 不成立；先對齊功能與可靠性再重測 |
| 唯一差異是更強的算法或 Numba 實作 | 把價值放在 solver 套件或算法研究，不必宣稱 runner 優勢 |
| AI 負載主要花在 GPU 張量計算／模型訓練 | 優先適配現有設備計算／調度生態，避免用 CPU worker 數作主要效能策略 |

## 9. 目前最該做的事情

你的補充使工作順序需要調整：**不是先完善 v2 架構，再找它的價值；而是先用一個小型替代性實驗，確認值得自建的邊界。**

下一個具體任務可以定義成：

> 使用一個完整可運行的專案 commit，保留同一個 MKP Numba solver，建立 joblib 和 Benchopt 的最小接入；核對實際工作量與端到端計時，測效能及一組必要失敗案例，輸出自建／整合的決策。不移植全部算法，不先實作 managed RNG，不新增完整 AI 平台。

這不是「再研究到萬無一失才開工」。它本身就是實作，而且直接降低你最在意的風險：花大量力氣重建已有且更合適的系統。

**最終判斷：你的研究工具可以有價值；但「三領域＋高併發」目前不成立為差異化理由。比較有依據的方向是先保留算法與研究資產，驗證薄整合是否足夠，再由真實效能或工作流程缺口決定保留多少自建核心。**

---

## 證據與範圍

### 專案來源（同一固定 commit）

以下來源來自本次及同一對話前一輪已讀的 GitHub 檔案；本次重新核對分支 SHA，未改動專案。

- **[R01]** v2 需求及實作計畫：`note/improve/v2/requirements-baseline.md`、`implementation-plan.md`。
- **[R02]** `machine/core.py`、`simulator/core.py`：task 展開、process pool、session、提交與驗證。
- **[R03]** `engine/bank.py`、`engine/assembly.py`：題庫與 shared-memory 組裝。
- **[R04]** `solver/BSMA_numba.py`：主迴圈、提早停止、evaluation_count、計時與程序內快取；本次讀取 1–580 行覆蓋此檔主要內容。
- **[R05]** `cli/run/support.py`、`tools/show.py`：整批執行後的結果寫入。
- **[R06]** `engine/builders.py`、根 `__init__.py`、完整 `solver/` Git tree：乾淨 checkout 的匯入依賴疑點。

固定快照：`https://github.com/cgit6/opus-solver/tree/8557dd02e2161513d34334413e00908ddd1ac224`

### 外部第一手來源

查閱日均為 2026-09-28。文件可能是可更新的 stable／latest 網址；正式實驗應另外固定套件版本與 commit。本文沒有把舊論文的加速比套到今天的版本，也沒有採用廠商宣傳的倍數作為跨專案效能排名。

- **[S01] Benchopt 官方首頁與功能範圍**：`https://benchopt.github.io/`
- **[S02] Benchopt — Get started**：`https://benchopt.github.io/stable/get_started.html`
- **[S03] Benchopt — Distributed run**：`https://benchopt.github.io/stable/user_guide/distributed_run.html`
- **[S04] Benchopt — Evaluating an iterative method**：`https://benchopt.github.io/stable/user_guide/iterative_solvers.html`
- **[S05] jMetalPy — Experiments**：`https://jmetal.github.io/jMetalPy/tutorials/experiment.html`
- **[S06] IOHprofiler 官方功能與分析範圍**：`https://iohprofiler.github.io/`
- **[S07] pymoo 官方功能與變數表示**：`https://pymoo.org/`
- **[S08] pymoo — Parallelization**：`https://pymoo.org/parallelization/index.html`
- **[S09] pymoo — Checkpoints**：`https://pymoo.org/misc/checkpoint.html`
- **[S10] Nevergrad — 官方首頁與混合變數示例**：`https://facebookresearch.github.io/nevergrad/`
- **[S11] Nevergrad — Optimization／executor／ask-tell**：`https://facebookresearch.github.io/nevergrad/optimization.html`
- **[S12] pygmo 官方定位與能力**：`https://esa.github.io/pygmo2/`
- **[S13] Optuna — Easy Parallelization**：`https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html`
- **[S14] Ray Tune — Running Basic Experiments**：`https://docs.ray.io/en/latest/tune/tutorials/tune-run.html`
- **[S15] Ray Tune — Resources**：`https://docs.ray.io/en/latest/tune/tutorials/tune-resources.html`
- **[S16] Ray Tune — Trial Checkpoints**：`https://docs.ray.io/en/latest/tune/tutorials/tune-trial-checkpoints.html`
- **[S17] EvoTorch 官方文件**：`https://docs.evotorch.ai/latest/`
- **[S18] EvoTorch — Problem Parallelization**：`https://docs.evotorch.ai/latest/user_guide/problem_parallelization/`
- **[S19] EvoX 官方倉庫**：`https://github.com/EMI-Group/EvoX`
- **[S20] EvoX 論文（作者第一手研究）**：`https://arxiv.org/abs/2301.12457`；本次讀取摘要與出版頁，不宣稱完成全文基準結果複驗。
- **[S21] EvoXBench 官方倉庫**：`https://github.com/EMI-Group/evoxbench`
- **[S22] Ray — Serialization／同節點零複製**：`https://docs.ray.io/en/latest/ray-core/objects/serialization.html`
- **[S23] joblib — Parallel／memmap／batch／oversubscription**：`https://joblib.readthedocs.io/en/stable/parallel.html`
- **[S24] Ray — Too fine-grained tasks**：`https://docs.ray.io/en/latest/ray-core/patterns/too-fine-grained-tasks.html`

### 未被本次證明的事情

沒有證明所有替代品完全符合你的每條需求；沒有證明任何方案在你的硬體上最快；沒有認定原參考模擬系統無效；沒有驗證外部使用者願意採用新的框架；沒有把「本次未找到某項功能」等同於「所有既有系統都做不到」。
