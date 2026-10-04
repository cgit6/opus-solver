# SCVRP Python／Numba 效能改善順序

## 原則

- 正式演算法為單檔 `solver/CDELS.py`；舊 Python solver 已移除。
- 舊行為由固定 fingerprints 與 test-only C++ oracle 凍結，不再保留第二套
  Python 演算法。
- 先補齊可執行題庫與 baseline，再宣稱求解品質不退步。Archive 中 16 組
  `RouteCap=8` A 題缺 customer，必須以 legacy owner=0 profile 獨立標記，
  不得誤稱為已修復的 Gurobi 資料。
- 每次只改一個小模組，通過逐代狀態與 RNG 差分後才進下一步。
- Legacy bug 暫不修改；避免把效能差異、算法差異與 bug fix 混在一起。

## 現況 profile

以 `P-n16-k8`、100 transitions 測得約 4.0–4.3 秒；線性估算完整
11,220 transitions 約 7.5 分鐘。

主要累積耗時：

- local search：約 88%
- two-swap：約 49%
- strong-drop：約 37%
- reinsertion：約 35%
- swap cost 計算：約 29%
- nearest non-transfer 掃描：約 20%
- reevaluation：約 9%

RNG 與 individual clone 不是目前主要瓶頸。

## 記憶體風險與量測基線

記憶體必須和執行時間一起作為硬性驗收條件。需要分開觀察「單一 solver
程序」、「多 worker 的總和」與「驗證 trace」；只看某一個程序的 RSS，可能
看不出 shared memory、子程序或 Python allocator 保留的高水位。

2026-10-04 的 A-n80-k10、RouteCap=2、MaxTransfer=1、seed 1 量測：

| 階段 | 程序 RSS | 相對載入 problem 後的增加 |
|---|---:|---:|
| problem 已載入、尚未建立 population | 143,512 KiB | 0 KiB |
| 建立 240 個 individuals 後 | 144,664 KiB | 1,152 KiB |
| 完成一個 generation 後 | 146,072 KiB | 2,560 KiB |

同一題一個 population 的 Python container／NumPy owned-buffer 估計約
1.05 MiB。這表示現有 80-customer 題目的 population 不是 140 MiB 基礎用量
的主因；主要基礎成本來自 Python 套件載入：

| 新程序載入內容 | max RSS |
|---|---:|
| 空 Python | 約 11.5 MiB |
| NumPy | 約 27 MiB |
| `mkp.solver.CDELS` | 約 145 MiB |

目前 `mkp/__init__.py` 與 `engine/builders.py` 會提早載入其他 Numba／SciPy
solver。`MachinePool` 使用 spawn process，因此多 worker 會放大這份基礎成本；
例如 8 workers 還有 parent process，不能只用單一 CDELS population 的大小估算
總記憶體。shared library 的唯讀頁可能由 OS 共用，所以容量規劃應量 aggregate
PSS，RSS 總和只當保守上界。

實際同時啟動 4 個只載入 CDELS 的程序時，RSS 總和約 573.6 MiB，但 aggregate
PSS 約 324.4 MiB，其中 private pages 約 265.8 MiB。這證明不能把 4 份 RSS
直接視為實體 RAM；不過每個 Python interpreter、module object、heap、RNG 與
population 仍是私有資料。現有 shared memory 只共用 ProblemBank 中明確放入
shared blocks 的 coords、demands 與 distance matrix，不會讓整個 worker heap
自動共用。

演算法本身也有隨題目放大的結構性風險：

- population size 固定為 `3 * n_customers`；每個 individual 又保存 O(n) 的
  routes、positions 與 transfer mask，因此 population 常駐空間是 O(n²)。
- `_new_generation` 執行期間，舊 population 與已接受的新 trials 會同時存在；
  最壞情況接近兩個 populations，再加一個暫時 mutant／trial。
- `process_trace=True` 會保留每代 digest／RNG checkpoint，空間隨 transition
  數 O(iterations) 成長；正式 Engine adapter 已關閉，但 dataset exact-validation
  會開啟。
- `ProblemBank` 會一次準備 spec 內所有問題，parent 同時保留原 model 與 shared
  memory copy；大型且多題時，distance matrices 的總和也可能成為瓶頸。
- `validate-run` 本身目前是逐 task 串行，不會同時執行 112 題；一般 Engine 的
  `--worker > 1` 才會以 process 數量放大記憶體。

### 記憶體改善順序

1. **先降低每個 process 的固定成本**：將 package exports 與 solver builders
   改為 lazy import，讓 CDELS worker 不載入未使用的 Numba／SciPy solver。這是
   不改演算法狀態、預期回報最高的第一項。
2. **加入 memory-aware worker 上限**：以可用 RAM、保留比例和單 worker 實測
   peak PSS 決定 worker 數；不得只依 CPU core 數。保留明確的 `worker=1`
   低記憶體模式。
3. **避免驗證 trace 無界累積**：正式 Engine 的 `process_trace=False` 不會保存
   每代 trace；exact-validation 才刻意 append 每代證據。長 trace 應改為
   incremental SHA-256／串流 checkpoint；C++ oracle 也應提供 aggregate 或
   JSONL 串流模式，避免 stdout、decoded JSON 與 comparison lists 同時常駐。
   這只改測試工具，不改正式算法。
4. **縮小 individual 狀態**：先獨立驗證 `positions` 使用 int32、transfer mask
   使用 bool／uint8；不得與 local-search cache 同批修改。
5. **用雙緩衝限制配置與碎片化**：保留 current population 作整代唯讀來源，
   逐 slot 覆寫預配置的 next population，完成後交換兩個 buffer；另外重用
   mutant scratch，並為可能不在 population 內的 legacy elite 保留獨立 buffer。
   這會讓記憶體上限可預測並避免每代重建容器，但同步 DE 本來就需要 current
   與 next 兩份狀態，因此不保證比目前「拒絕時共享舊 target」的峰值更低。
6. **Numba SoA 作為大型題目的正式結構解法**：固定寬度 routes、positions、
   masks 與 capacities 使用連續陣列和雙 buffer，讓 O(n²) 的常數可預測，並消除
   Python list／tuple 配置流量。

### 記憶體驗證 gate

每個記憶體改動都必須同時通過：

1. 原有 canonical process trace、RNG、objective、routes 完全一致。
2. 分別記錄 parent、每個 worker、native oracle，以及 aggregate peak RSS/PSS；
   不以單一程序數值代替整批用量。
3. worker=1 連續執行至少 20 個同尺寸 tasks，warm-up 後不得呈現持續線性成長。
4. worker=1、2、4（硬體允許時再含 8）量測總 peak，確認 worker 上限符合設定的
   RAM budget，並至少保留 20% 系統空間。
5. 至少量 n=16、32、48、64、80；未來加入更大 instance 時以 n² 模型檢查
   實測斜率，不能只以 A-n80 推估後宣稱已解決。
6. benchmark 必須分開 `trace=False` 的正式 Engine 與 `process_trace=True` 的
   exact-validation，避免把測試證據成本誤算成正式算法成本。

## Phase A：保持完整算法歷程一致的 Python 優化

目標是 RNG draw、候選順序、tie-breaking、每代 population 與最終結果皆不變。

候選項目：

1. 建立 core 專用 fast reevaluator，避免通用 validator 的 tuple/set/sort 與重複配置。
2. 將 distance、demand、fixed-route owner 建立適合 hot loop 的只讀 scalar view。
3. 對未發生 mutation 的區段快取 active edges／nearest non-transfer 派生資料；
   每次 swap、insert、remove 或 transfer-mask 變動後立即失效。
4. 重用已計算的 SA `exp(delta/T)`；保持 RNG draw 次數不變。
5. 最後才評估 scratch buffer 與暫存陣列重用。

### Phase A-1：distance matrix 零複製 memoryview（已完成）

2026-10-04 將 CDELS hot loop 的距離讀取由 NumPy chained indexing
`distances[row][column]` 改為共用原 NumPy buffer 的唯讀
`memoryview[row, column]`。沒有複製距離矩陣，也沒有改動候選順序、RNG、
tie-breaking 或 objective 計算。

同機器、相同測法的前後結果：

| Case | 修改前 | 修改後 | 改善 |
|---|---:|---:|---:|
| P-n16，100 transitions，seeds 1–5 中位數 | 4.945 s | 4.488 s | 9.2% |
| A-n80，seed 1，單一 generation | 10.281 s | 9.583 s | 6.8% |

一致性證據：

- memoryview 與 `SCVRPProblem.distance_matrix` 共用同一 buffer，且為唯讀。
- P-n16、seed 1、111 transitions 與 C++ oracle 的完整逐代 process trace
  為 `exact_match`。
- P-n16、seed 1、11,220 transitions 長測通過；11,221 個世代的完整 process
  SHA-256 仍為
  `2a6adf93d6f20b37fc18fbef1831dffa83a8c8b9d97b6edcf30cb44d6f07aa1e`。
- SCVRP／CDELS 回歸測試：227 passed、4 個需顯式啟動的昂貴測試 skipped；
  完整 replay 另以環境變數啟動並通過。

結論：此項保留。下一個候選是 active-neighbor 衍生狀態快取，但需先設計
route／transfer-mask 變動後的精確失效規則，不可直接加入永久 cache。

### Phase A-2：two-swap 當輪鄰居 scalar cache（已完成）

2026-10-04 將 two-swap 中同一個 `i` 的左右鄰居改為每次進入 restart
`while` 時讀取一次；掃描每個 `j` 時直接讀入四個 scalar，不再呼叫會建立
二元素 tuple 的 immediate-neighbor helper。接受 swap 後會回到 `while` 開頭，
所以 cache 正好在 route 狀態可能改變時重讀，沒有跨 mutation 保存 stale 狀態。

A-n80-k10、RouteCap=2、MaxTransfer=1、seed 1 的單一 generation：

- immediate-neighbor tuple 呼叫由 4,027,853 降為 100,055，減少 3,927,798
  個 tuple，約等於 209.8 MiB 的邏輯配置流量。
- 三次執行中位數由 8.283 s 降為 8.041 s，約改善 2.9%。這是簡單的局部
  scalar cache，因此即使改善未達複雜 cache 的 10% 門檻仍予以保留。
- generation best cost 仍為 1943，RNG state 仍為 1404805482，draw count
  仍為 760115，完整 generation digest 仍為
  `859e44995e1e6399da76ec86214166ef6b43e71d9cc4857843289512dff2088d`。
- local-search／初始化測試 20 passed；小題目逐欄 C++ generation oracle 及固定
  fingerprint 7 passed；110／111 transitions 的第一次降溫邊界 2 passed。

結論：此項只重用當輪不變的 scalar，不改候選、RNG、成本計算順序或 selection，
保留。下一個 gate 才評估 nearest-nontransfer scratch/cache，不與本項混改。

不可直接做的簡化：

- 不可直接刪除兩次 reevaluation；local search 中存在刻意保留的 stale-state 語意。
- 不可快取 capacities／feasible 等 legacy 可能暫時過期的欄位。
- 不可因 genome 重複就跳過 local search，否則可能跳過 RNG draws。

### Phase A 驗證 gate

每個小改動依序執行：

1. seeds 1–3、111 transitions，完整 canonical process trace 與 RNG 差分。
2. seed 1、11,220 transitions，aggregate digest 必須維持
   `2a6adf93d6f20b37fc18fbef1831dffa83a8c8b9d97b6edcf30cb44d6f07aa1e`。
3. seeds 1–10 最終 routes、objective、feasibility 與 RNG fingerprints。
4. 96 個直接設定及 16 個 legacy-compatible 設定的跨題 oracle／baseline。
5. warm-up 後至少 5 次 benchmark，以中位數判斷；建議單項改善至少 10–20%
   才保留複雜快取。

## Phase B：允許改變搜尋歷程的流程優化

例如縮小候選鄰域、trial dedup、early reject、改搜尋順序或平行 population。
這些做法可能錯過原本改善，無法事先保證所有題目的求解品質不下降。

必須等 112 個設定的跨題 baseline 完成後，再逐項實驗；16 個 owner=0
相容設定的統計需另外標示。每個
instance × seed 要配對比較：

- feasible rate 不得下降；
- 若採嚴格門檻，同迭代 objective 不得更差；
- 同 wall-clock 報告 gap 的 median、p95、max；
- 報告 win／tie／loss，而非只看平均值。

未達品質門檻的流程優化不得成為正式預設。

## Phase C：Numba 版本

Numba 版本以「最終確認的 optimized Python」為唯一行為規格。

目前 dataclass、`list[list[int]]`、動態 insert/pop 與 Python callback 不適合直接
`njit`。應改為固定寬度 SoA arrays：

- `routes[population, vehicle, customer]`
- `route_lengths`
- `positions[population, 2, customer]`
- transfer masks、capacities、cost、feasible flags
- 明確的 MSVC `uint32` RNG state 與 draw count

Numba 約束：

- `fastmath=False`
- 不平行共享 RNG 流程
- insert/pop 以固定陣列 shift 實作
- `exp()` 必須先用邊界向量與 Python 版本驗證
- compilation warm-up 與 steady-state benchmark 分開計算

### Numba 驗證 gate

1. 初始化完整狀態一致。
2. 每個 local-search／transfer 模組逐欄一致。
3. 短跑每代完整 population、best、RNG 一致。
4. 長跑固定 checkpoints、final state、RNG 一致。
5. 至少一次完整 process trace 與 optimized Python 完全一致。

以上全部完成後，才進入 Legacy bug 的獨立評估與修正版 solver 設計。
