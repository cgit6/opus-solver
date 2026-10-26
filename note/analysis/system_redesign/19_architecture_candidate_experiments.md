# 19｜架構候選實驗與證據範圍

整理／封存日期：2026-10-24。本章接續 D79–D80 後的候選比較，記錄已做研究，不選定新架構、不新增決策，也不是正式 G2／G3 驗收。較早 [16](16_process_lifecycle_experiment.md)、[17](17_invocation_comparison_experiment.md) 的方法、數字及當時適用政策保留；本次沒有重跑它們。

## 目前能說到哪裡

第 1（呼叫與執行）、第 2（共用題目資料）、第 4（交付與保存）單元已有下列候選證據，但尚未選新組合。第 3 單元設定政策已確認，正式 API、交付與完整 schema 仍待細化；第 5／6／7 單元仍待討論。排程責任、程序／執行緒及 binding／IPC 的維度依 [14](14_python_cpp_invocation_and_failure_replay.md#架構狀態與比較維度) 分開，不能把本實驗稱為「Python 派工對 C++ scheduler」。

不變需求與原交接機制的差異依 [08](08_cpp_invocation_and_shared_memory.md#不變需求與原交接基線)；保存責任、原 Python 基線及返回／所有權差異依 [07](07_history_return_and_storage.md#已確認交付需求與保存基線)。測過 native 獨立輸出器、直接共用 Bank、prefork 或唯讀頁面，不代表自動修改 D18／D19／D34 或 D74–D77。

## 證據批次與來源

原 README／REPORT 及 raw 是細項口徑的來源；本章只整理可追查結論，不用摘要取代原記錄。

| 批次 | 當時證據 | 原始說明與摘要 |
| --- | --- | --- |
| gate1：小型正常控制 | 兩種拓撲 × 1／2／4 執行單元，共 6 配置；288 task、4,896 快照。另有 16 次 smoke、272 快照及 24 個比較器負向控制，不混入前數。 | [README](evidence/architecture_candidates/gate1/README.md)、[audit](evidence/architecture_candidates/gate1/audit_results.json) |
| gate2：歷史故障控制 | 6 情境 × 2 拓撲 × 2／4 單元 × 3 輪，共 72 故障案例；當時核對 168 份完整文件、5,544 快照。名稱 gate2 不等於 [11 的正式 G2](11_migration_and_verification.md)。 | [README](evidence/architecture_candidates/gate2/README.md)、[final audit](evidence/architecture_candidates/gate2/audit-final-72.json)；另保留 first-24／repeated-48／all-72 的原階段摘要。 |
| comparison：效能與記憶體控制 | 48 配置各 5 個計量批次，共 240 批；另 8 個 memory run。原稽核當時核對 2,336 份完整輸出，共 1,194,241,580 bytes。 | [REPORT](evidence/architecture_candidates/comparison/REPORT.md)、[README](evidence/architecture_candidates/comparison/README.md)、[raw benchmark](evidence/architecture_candidates/comparison/benchmark_results.json)、[combined audit](evidence/architecture_candidates/comparison/combined_audit.json) |
| comparison：補充故障與可行性 | 補充故障 24 案例做兩輪，共 48；另真 CDELS 對照、原始 global RNG 負例、clean prefork 與唯讀頁面探針。 | [first](evidence/architecture_candidates/comparison/extra-first/results.json)、[repeat](evidence/architecture_candidates/comparison/extra-repeat/results.json) 及下節各 raw。 |

gate1 使用小型 MKP 控制核心，每輪翻轉一個物品；task 私有 RNG、scratch、歷史與結果，獨立 Python reference 由完整編碼重算 fitness、feasible、load、best 及每份快照。16 個獨特輸入是兩題 × seeds 1–4 × 更新 0／32，初始化不算更新。原稽核另記 1,028 次保留結果重查、36 波更新區間重疊；同步點只證明 task 同時處於更新區間，不等於指令級平行或加速。這不是正式 CDELS、OS 唯讀保護或大題 RAM 驗收。

gate2 加入真實 C++ 可捕捉例外、原生 abort、實際保存路徑錯誤、JSON TypeError，以及保存／最終通知與退出交錯。312 個已派 task 中，156 已確認交付、12 已知算法例外、24 保存錯誤、120 交付未確認；另 120 個預定輸入未派。已保存但缺通知的 12 份完整文件仍未確認，不靠掃檔補登。當時 24 次保存錯誤清理後同 PID／TID 接新題、其他工作繼續，144 個自有執行程序最後退出；不是任意強殺後一定 finally、任意 IPC 或 D40 全部分支驗收。該批 controller 對已知算法錯誤或失去 host 都採測試安全停止，不因此替未知退出定正式原因或政策。測試 watchdog 不是產品 timeout。

## 候選實際比較了什麼

threads 原型是在一個 spawned execution host 內，由 **Python `ThreadPoolExecutor`** 呼叫釋放 GIL 的 C++ 核心；不是 C++ scheduler。threads 共用一個 immutable typed C++ Bank；processes 是多個 spawned host，各自準備一個 Bank，並未用 SHM 傳輸共用題目。管理端只收小份狀態／路徑，不收完整歷史。不能把「processes 各有副本」的成本推成所有多程序共享方案都相同。

保存控制比較 Python 與獨立 C++ 輸出元件：相同 canonical JSON、exclusive create、flush／fsync／close，完整結果所有權持有到保存結束。算法仍不寫檔。這只是候選對照；若採 native 保存、完整 history 不再轉成 Python 物件，須先列相對 D18／D19／D34 的返回、所有權與錯誤映射差異待確認，不因這份實驗默默取消原 Python 基線。

效能矩陣為 2 題目尺寸（64／2,000 points）× 2 執行單元數（1／4）× 3 工作量 × 2 拓撲 × 2 輸出元件，共 48 配置。每配置一批暖機後量 5 批，每批 8 task、seeds 1–8，打亂順序並綁定當時可用的前 4 CPU。工作量為 short（256 records × 4 steps）、compute-heavy（8,192 × 256）、history-heavy（65,536 × 2）；matrix 是 `uint64` 的 n×n 資料，task scratch 為 8 KiB。這份效能歷史是控制用數列，不是完整 CDELS 種群歷史；gate1／fault 核心才提供完整 MKP 狀態對照。

### 計時、記憶體與完整性限制

- 批次計時包含派工、計算、結果轉換、序列化、fsync 保存與最終訊息；不含編譯、程序啟動、題目準備、reference 計算及完整輸出核對。啟動時間僅每個「拓撲／題目尺寸／執行單元數」組合觀察一次，不依 workload／saver 重複；不是 48 配置各五次的計量樣本。
- 計時時另一種拓撲已啟動但閒置；記憶體另跑、每次只留一個候選，4 task 都保留結果到 barrier 後才保存，這個 barrier 不在計時批次。PSS 取 controller＋執行程序，約 5 ms 取樣及 checkpoint，每配置一次 run、10–16 個樣本；只稱 sampled max，不是保證真實峰值。這是薄原型，不含完整應用、CDELS 種群成長或任意歷史形態。
- 第一個 benchmark 因 smaps header parser 出錯，在計量前中止；修正後重跑到 `performance-measured`，失敗那次不是有效計時。未使用的 `performance-output` 也不是本表輸出。
- 獨立 `perf_reference.py` 及來源 SHA 綁定的 reference 當時逐位元核對 1,920 計量＋384 暖機＋32 memory 完整文件＝2,336，包含 metadata／checksum，另做獨立 RNG affine-exponent 核對。本次只讀核對 raw 摘要及封存 SHA，沒有重新讀取未封存的大份完整內容。
- fsync／排程存在明顯波動，5 次計時及單次 memory 不能推論普遍排名、正式系統效能或所有題目的加速／節省比例。

例如 2,000 points、4 單元、8 task 的批次中位數／範圍（ms，5 次）如下；只供對回原 REPORT，不是選型建議。

| 拓撲／輸出 | compute-heavy | history-heavy |
| --- | --- | --- |
| processes／Python | 64.94（59.26–87.54） | 54.23（41.82–124.96） |
| processes／C++ | 65.34（60.99–90.41） | 48.00（35.41–68.93） |
| threads／Python | 58.54（49.80–140.80） | 106.59（82.21–147.64） |
| threads／C++ | 68.50（52.67–73.82） | 41.61（31.75–88.21） |

同尺寸 matrix 為 32,000,000 bytes，這組 threads 一份、processes 四份；對應 ready／sampled-max PSS（MiB）分別為 processes-Python 183.79／202.66、processes-C++ 183.81／190.91、threads-Python 64.49／81.47、threads-C++ 61.08／68.23。這不是 SHM 或 prefork 多程序的記憶體比較。

## 補充故障與未決政策

兩批共 48 案例保存 planned inputs、assignments、events、controller report、錯誤與輕量結果；包含完整文件但 IPC 截斷仍未確認、部分文件後退出仍部分／未確認、真 JSON TypeError 後錯誤通知截斷造成原因遺失等。截斷測試關閉了寫端，不涵蓋寫端持續開啟的有界讀取、任意畸形 frame 或正式 supervisor。

cleanup 分支用真實軟體 exception 加刻意持有 Result，以 weakref／native 計數檢查，不模擬任意 heap corruption。比較過兩個競爭提案：立刻退休受影響 host，或讓已知健康同伴先完成後退休。threads 在立刻退休時可連帶失去同 host 其他尚未交付 task；2／4 單元各有 1／3 題，processes 的其他 host 可完成。先完成健康同伴的提案沒有等待上界，也不能套到未知記憶體破壞。**兩案尚未定案**，不可任選一案寫成 D40 新恢復政策。

另一候選是 worker 先保存獨立錯誤 artifact，再通知主管；該負例中可留下原因／traceback，主管沒有自動讀檔補登。它只是未採用的留因提案，不代表已決定正式錯誤紀錄時序、任意 kill 保證或硬體備援；本章不制定這些政策。

## 真 CDELS、RNG 與共享可行性

| 探針 | 當時觀察 | 不能推成什麼 |
| --- | --- | --- |
| [真 CDELS](evidence/architecture_candidates/comparison/real_cdels_results.json)／[來源](evidence/architecture_candidates/comparison/real_cdels_check.py) | 現有 Python CDELS 對原 C++ fresh-process oracle；P-n16-k8（route capacity 2、transfer 1），seeds 1／2、updates 0／3／111，再重複兩個短案，共 8 runs、6 個 unique inputs。每 run 的 12 欄全部對上，含終止、停止原因、generation／transition、停滯、temperature IEEE754、RNG 狀態／draw count、result、完整 trace SHA、逐代 digest、RNG checkpoints。 | 不是 112 配置題庫重驗，不是 thread-safe CDELS port，也沒有真 CDELS 併發驗收。原 oracle generation 含初始化，不能藉此改正式 D58。 |
| [原始 global RNG 負例](evidence/architecture_candidates/comparison/legacy_rng_interleave_results.json)／[來源](evidence/architecture_candidates/comparison/legacy_rng_interleave.py) | 未修改的 `compat_rng.cpp` 在獨立 library 順序交錯：A seed 1 原應 `[41, 18467]`，B seed 2 為 `[45, 29216]`；A 被 B 干擾後變 `[41, 29216]`。 | 每 task 重設 seed 不等於 RNG 私有。這是無效共用接線的負例，不是目前 fresh-process oracle 的 bug，也沒有以 C++ 併發未定義行為做測量。原核心 NP／generation 等全域狀態仍須按 task 重構後才可談 threaded port。 |
| [clean prefork](evidence/architecture_candidates/comparison/prefork_results.json)／[來源](evidence/architecture_candidates/comparison/prefork_check.py) | Linux 乾淨單執行緒 supervisor 準備 Bank 後 fork 4 children；正常計畫退休後補位繼承同 Bank，5 份完整輸出對 reference，supervisor＋4 children 的 matrix mapping PSS 合計 31,250 KiB。 | 只證明這個乾淨實驗可行，未選 fork、未比效能、不是算法錯誤後續跑，也沒證明初始化任意 NumPy／ML／多執行緒環境後 fork 安全；正式管理隔離仍未解。 |
| [唯讀頁面](evidence/architecture_candidates/comparison/readonly_results.json)／[來源](evidence/architecture_candidates/comparison/readonly_check.py) | 獨立 page-aligned mmap 填入資料再設唯讀；讀／寫／再讀 return code 為 0／-11／0，讀值和均 2,016，controller 存活。 | 只證明探針頁面保護生效，不是正式 Bank 布局、共享交接、所有權或 D76 全面驗收。 |

## 封存完整性與本次工作

[歸檔說明](evidence/architecture_candidates/README.md) 與 [manifest](evidence/architecture_candidates/manifest.json) 保存 411 份原始來源、摘要及輕量案例，共 4,487,283 bytes 原始內容。403 份按原位元保存；8 份刻意截斷、無尾端換行的負向 JSON 以 `.base64` 封存，解碼後核對原 SHA／大小，不冒稱有效 JSON 或實體原位元 JSON 副本。原 JSON 絕對路徑原樣保留供 provenance。

本次核對來源／摘要／連結／數字與封存 SHA，從原 raw 只讀重算 48 組計時摘要（240 批）、8 memory 摘要及補充案例計數；沒有編譯、求解、故障注入、重跑原 audit 或重新核對未封存的 2,336 份完整文件。大型輸出及生成物不放入 Git，原三個暫存來源與 16／17 研究來源不動。只讀驗證方式、原腳本會寫檔的警告，以及只能複製到全新 tmp、依賴僅 `pip --target` 到 tmp 的重跑約束，均見歸檔說明。

目前停止於候選證據整理。後續須由使用者確認比較差異與方案，再細化正式 API／所有權／停止與未知退出／保存留因／驗收計畫；不以本章取代未定政策，也不把七個單元宣稱全部完成。
