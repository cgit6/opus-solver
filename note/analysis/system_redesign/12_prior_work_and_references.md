# 12｜更早的算法研究、架構討論與來源

狀態：歷程整理與目前檔案核對，不是重新驗收報告。用於解釋這次重構從哪裡來，不把舊提案全部變成新需求。

## 1. SCVRP 移植的起點

最初目標是把舊 archive 中的優化問題與算法移植入現有流程，要求相同 seed、固定迭代下，初始化、搜尋過程與最終解一致，不只比較 objective。

歷程中先選 SCVRP，保留 legacy 行為與 bug 作對照；之後才討論 CVRP。曾使用 C++ compatibility kernel／oracle，不等於當時已完成純 Python；後續才逐模組完成 Python 邏輯與正式入口切換。

現在 [SCVRP 驗證狀態文件](../../study/scvrp/validation_status.md) 記載正式 `cdels` 的算法／adapter 在 [solver/CDELS.py](../../../solver/CDELS.py)，舊 C++ 由測試工具作 oracle。這不表示本次已建立新的 C++ 正式求解模組。

## 2. 題庫數量及 16 個異常的釐清

[SCVRP 題庫索引](../../study/scvrp/README.md) 及驗證狀態記載：

- 7 個 base instance，各 16 組參數，共 112 個 SCVRP 設定。
- 96 組原始 fixed-route 完整。
- 另外 16 組原始 fixed-route 缺 customer；原始檔仍保留。
- 後續加入明示的 legacy owner=0 相容處理，因此 112 組可建模，不代表 16 組原資料被找回或修好。
- 部分 A-n32 的歷史重播支持 owner=0；其他相同缺失型態的套用仍有來源推論邊界。

所以「112 組」是總設定數，「16 組異常」是其中子集，不是只有 96 組檔案被移入。

既有單題多 seed 與完整單題長測，不等於全部 112 組跨題長測。本次未檢查使用者本地長測的所有產物，也沒有重跑；不能補宣稱全題已通過。

使用者曾要求跨題驗證提供可執行命令、自行啟動。命令與 output／plan 不可混用的說明保留在 SCVRP 索引；不在這次文件整理啟動昂貴驗證。

## 3. 不可行結果與 legacy +100

現有 SCVRP 文件記載 `raw_objective`、`legacy_penalty`、`legacy_search_score` 三值，以及不可行時 +100 的相容契約。

新架構已確認真實目標與搜尋分數分開。遷移時必須明確映射既有結果，不能讓不同名稱暗中指向不同數值；也不能為了統一欄位，改掉 legacy 的搜尋接受與選擇行為。

統計如何使用不可行結果仍待討論，不因問題已能保存三值就自動解決。

## 4. CDELS 單檔、workspace 與資料布局研究

使用者要求可閱讀、註解白話精確、算法邏輯集中一檔；曾參考 Problab 遊戲邏輯的主結構與輔助函數安排。舊拆分的 Python 算法檔後來移除，以 `CDELS.py` 作正式基線。

後續工作另開副本研究，沒有授權就不動原基線。workspace 副本後續命名為 [CDELS_2.py](../../../solver/CDELS_2.py)。

曾討論／實驗的項目包括：

- 距離矩陣 memoryview，避免轉成額外 Python 物件樹。
- 配置流量與同時存活記憶體的區分；工作緩存初始化後重用。
- 型別壓縮；使用者提約 2,000 點與 uint16 方向。仍需檢查索引、哨兵及溢位，不能把所有數值無條件轉小整數。
- population／trial pool、current／next 引用交換、連續 backing storage。
- routes 的 packed uint16、flat Python list、Copy-on-Write。
- 鄰居 tuple、Local-search 小 list、通用 reevaluator 的熱路徑配置。

Python 中壓縮格式或固定 buffer 不必然更快；逐元素 Python 包裝／索引成本可能抵消省空間收益。使用者目標是盡量同時省空間與加速，沒有接受「只以變慢換省空間」作一般結論。

上述特定實驗的詳細證據在 [效能計畫](../../study/scvrp/performance_optimization_plan.md) 與 [固定 trial pool 問題](../../study/scvrp/improved/fixed_trial_pool_performance_issue.md)。這些文件可能記錄不同歷史階段，不能把其中未更新的待辦，直接當作現在沒有對應程式。

## 5. Numba 與 C++ 效能比較

目前檔案包括 [CDELS_numba.py](../../../solver/CDELS_numba.py)、[CDELS_2_numba.py](../../../solver/CDELS_2_numba.py) 及 [CDELS_packed_numba.py](../../../solver/CDELS_packed_numba.py)，對應註冊可在 [engine/builders.py](../../../engine/builders.py) 核對。

先前開發方向包含逐模組轉換、mutation／crossover、把整代／多代迴圈放進 native 執行、減少 row view 和呼叫成本，再比初始化、過程、結果與 RNG。

「一次執行多代」指減少語言邊界的順序執行，不表示把多個個體並行更新。並行會牽涉 RNG 與依賴，不能只為速度改掉原算法。

過去討論過 Numba 比 C++ 慢約 25% 等個別量測，但不能擴大成 Numba 對所有問題必定慢固定比例。本次沒有重跑；後續需分開編譯／暖機、算法、紀錄、資料交接及整場輸出時間，才公平比較。

## 6. CVRP 與原始碼完整性

早期因 CVRP archive／來源完整性疑慮延後，後續專案已有 [CDELS_CVRP.py](../../../solver/CDELS_CVRP.py)、[problem/cvrp.py](../../../problem/cvrp.py) 及對應設定／測試。

由現有 CDELS／SCVRP 邏輯形成 CVRP 算法，不等於證明已還原來源缺失的舊 CVRP executable 實驗。能否重現特定舊歷史結果仍取決於原規則與來源證據；本次不重新解壓或認證 archive 完整性。

## 7. MKP 算法命名與共用實作

曾依使用者要求將 MKP Numba 算法改為各自維護、不依賴 `_mkp_numba_common.py`，並命名為 [BSCA.py](../../../solver/BSCA.py)、[HSMSCA.py](../../../solver/HSMSCA.py)、[BSMA.py](../../../solver/BSMA.py)，同步註冊與設定路徑。

這是算法實作可讀性與維護選擇，不表示不能定義共同的任務或解狀態資料概念；也不授權本輪抽回共用熱路徑函數。

## 8. 連續問題與書籍算法整理

先前從書籍程式壓縮包整理連續／工程問題及多種算法，要求以來源作 oracle，逐步確認後再接 adapter／registry。

目前問題類型在 [problem/builders.py](../../../problem/builders.py) 註冊為 `continuous`，具體 objective／constraint 在 [continuous_objectives.py](../../../problem/continuous_objectives.py) 與 [continuous_constraints.py](../../../problem/continuous_constraints.py)。單題 YAML 指定 objective、維度、範圍等，不把每題都做成一個全新問題類型。

本次盤點現有 `configs/problems/continuous/` 是 27 份 YAML。較早對話中「27 加 4」是來源盤點討論口徑，不能直接據此宣稱現有已有 31 份正式註冊題目，或反過來不查來源就宣稱遺失 4 題。若要追到來源數量與變體，需另作映射盤點。

目前可核對到 ABC、BOA、GOA、GSA、MFO、SMA、SOA、SSA、TLBO、WOA 等算法註冊與 book oracle 測試檔。測試檔存在不等於本次已跑過全部測試。

## 9. Problab 的參考，不照搬責任

本輪唯讀追查 `/home/sean/work/problab_v0510`：

| 來源 | 實際可參考內容 | 不能推論成什麼 |
| --- | --- | --- |
| [sdk/buf/buffer.go](/home/sean/work/problab_v0510/sdk/buf/buffer.go) | 工作緩存、flat screen storage、Act 快照及 reset 保留容量。 | 完整歷史可不佔空間；或配置永遠不會擴容。 |
| [sdk/slot/game.go](/home/sean/work/problab_v0510/sdk/slot/game.go) | 新 spin 重設並重用工作狀態。 | 可以每次優化迭代清掉要永久保留的舊紀錄。 |
| [sim.go](/home/sean/work/problab_v0510/sim.go)、[SpinRecorder](/home/sean/work/problab_v0510/recorder/spin_recorder.go) | 大量模擬逐局累加統計，不保存所有局的完整 DTO。 | 滿足我們全部任務完整歷史的證據。 |
| [devsim.go](/home/sean/work/problab_v0510/devsim.go) | 詳細模式限制 1–5,000 局，累積結果後一次返回。 | 5,000 是 byte 上限；或可保障大型優化任務不 OOM。 |
| [dto/dto.go](/home/sean/work/problab_v0510/dto/dto.go)、[machine.go](/home/sean/work/problab_v0510/machine.go)、[Spin HTTP 入口](/home/sean/work/problab_v0510/server/api/v1/spin.go) | 求解結果先轉 DTO，HTTP 入口取得後才輸出 JSON；集中複製盤面等資料，再由 DTO 取快照切片。 | DTO 必須輸出 Web、完全零複製，或已證明多程序保存更快。 |

Problab 的 AddAct 同時更新分數累計與 act／step／round 狀態；本系統 addAct 已確認只記錄，因此不照搬這部分。

遊戲 demo 的 isSim 可讓外部 Snapshot 返回 nil，但不代表全套核心 Act／screen 記錄都關閉；不能直接據此決定本系統布林方向。

這次參考是原始碼閱讀，沒有修改 Problab 或執行其模擬測試。本機外部路徑不隨本 repository 一起分發。

後續借用的是「計算 → 結果 DTO → 外層輸出」的分工，可將 HTTP 輸出改為 Python 文本輸出；不是把 Problab 的同程序 goroutine 當成本系統跨程序交付的性能證據。worker／主程序保存與異常規則另見 [15](15_task_failures_and_result_storage.md)。

## 10. Redis／背景寫入討論

曾查閱 Redis 官方 [持久化](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)、[記憶體政策](https://redis.io/docs/latest/develop/reference/eviction/) 與 [pipelining](https://redis.io/docs/latest/develop/using-commands/pipelining/) 文件。

討論結論不是 Redis 一定慢，也不是它已證明比較快，而是沒有實測、且接收資料與同步磁碟是不同保障。若全部歷史留在 Redis，仍要處理容量；若搬出後刪除，又多了交付／確認流程。

最後使用者選擇先不導入，採 [07 的一次回傳設計](07_history_return_and_storage.md)。不在此另立 Redis 待實作任務。

## 11. 較早的系統提案如何處理

v2 曾提出 managed RNG、PCG32、多 stream、checkpoint、SQLite、發布與恢復狀態機等廣泛方案。後續使用者要求回到責任邊界、避免用資料結構及版本機制代替責任。

本輪保留高併發、原始結果、seed 可追蹤、小步遷移與未完成任務重跑的需求；不把上述大型技術提案當作已批准實作清單。具體清單以 [決策紀錄](design_decisions.md) 為準。

Benchopt／第三方框架曾作參考；目前沒有決定整個專案遷移到它們，也不把一般功能是否「有研究創新」和本輪責任設計混在一起。

## 12. 不屬於這次架構變更的歷史工作

Git 大檔被拒絕、清理提交與推送，以及逐字稿匯出，屬於 repository／研究資料維護，不是本輪要設計的新求解行為。

原始對話保留在 [逐字稿](../../codex_conversation_transcript_2026-10-14.md)；本次只讀其相關內容，不重新匯出、不更改完整性宣告、不操作 Git 提交。
