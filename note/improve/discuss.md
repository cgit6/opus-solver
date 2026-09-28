---
artifact_type: socratic-knowledge
schema_version: 2
id: "20260913-optiforge-architecture-improvement-discussion"
title: "Optiforge 架構優化討論紀錄"
status: provisional
verification: source-backed
mode:
  - A
  - D
topics:
  - "optimization architecture"
  - "reproducibility"
  - "RNG seeding"
  - "parallel execution"
  - "solver and problem registration"
aliases:
  - "Optiforge 優化討論"
  - "RNG 重現性決策"
created: "2026-09-13"
updated: "2026-09-13"
---

# Optiforge 架構優化討論紀錄

## 快速檢索卡

- 核心問題：比較 Optiforge 與參考 Slot 模擬系統，逐題釐清可重現性、擴充性、平行執行與模組邊界的設計決策。
- 當前結論：固定迭代停止可提供有條件的精確重現；時間停止必須保留，但不保證結果相同。
- 關鍵爭點：task seed 的身分、worker 與 RNG 的關係、停止條件、execution fingerprint，以及 solver 內部平行化。
- 適用於：Optiforge 的實驗組裝、RNG、Machine、Simulator、Experiment 與 replay 設計。
- 不適用於：尚未實測的跨硬體 bitwise 一致性，以及尚未討論完成的 solver 內部平行 RNG。
- 待驗證：不同 solver／param variant 是否共享 seed、平行 solver 的 RNG 子串流，以及 exact replay 的自動化測試矩陣。

## 記錄規則

- 每個已形成結論的議題立即新增一個 block，不等待整場討論結束。
- block 保留當時的問題、攻防、決策過程與結論；後續即使出現衝突，也不回寫舊 block。
- 新結論若修正或推翻舊結論，另開新 block，並標明它與舊 block 的關係。
- 每個 block 使用 Asia/Taipei（UTC+08:00）時間，記錄該次結論形成的時間點。
- 「當時結論已確認」只代表該回合已形成決策，不代表後續不能推翻。

## 核心問題

目前系統以可重現實驗為首要價值，solver/problem 註冊便利性次之；平行吞吐是效能需求，清楚邊界則是約束其他設計的原則。討論採逐題辯論，每題形成結論後保存完整但精簡的演化脈絡。

## 形成的知識

### D01｜RNG 停止條件與重現性

- 討論時間：2026-09-13 09:40:58 +08:00
- 狀態：當時結論已確認
- 討論問題：相同初始 seed 是否應保證實驗得到完全相同的結果，以及 worker 數量與停止條件應如何影響這項保證。
- 初始主張：相同 seed、RNG 算法與 RNG 消耗次數應產生完全相同的結果；併發執行可能需要從初始 seed 派生 worker seed。
- 關鍵挑戰：若 seed 綁定 worker，task 分配會隨 worker 數與排程改變；若使用 `max_seconds`，即使同一裝置也可能因執行進度差異而在不同迭代停止。
- 決策過程：先確認現行程式是在排程前按邏輯 task 派生 seed，而不是讓 worker 持有持續演進的 RNG；再用時間停止作為反例，將無條件的精確重現主張收縮為兩級契約；最後排除跨裝置結果一致性的要求，並補入 execution fingerprint 前提。
- 結論：
  1. task seed 必須在排程前由邏輯 task 身分派生；外層 scheduler 與 worker 不應持有會影響結果的共享 RNG 狀態。
  2. `max_iterations` 在 problem、solver、參數、程式、依賴、RNG 與 seed 派生規則一致時，可提供 exact replay；改變外層 worker 數與完成順序不應改變結果。
  3. `max_seconds` 必須保留，但只能提供 traceable run；不保證迭代數、RNG 消耗量或最終結果相同。
  4. 跨裝置執行不承諾完全相同的結果。
  5. 結果應保存 execution fingerprint，至少能追溯 problem 資料、solver 設定、停止條件、base/task seed、seed 派生版本、RNG、程式版本與關鍵依賴版本。
- 主張變化：`相同 seed 即完全重現` → `worker-independent task seed` → `固定工作量才保證 exact replay` → `跨裝置排除，時間停止降級為 traceable run`。
- 適用邊界：目前結論針對外層 task-level multiprocessing；尚未涵蓋 solver 內部自行平行運算、非確定性數值 kernel 或不同硬體環境。
- 待處理問題：不同 solver／param variant 是否共享同一 task seed；solver 內部平行化時如何派生 RNG 子串流；execution fingerprint 的必要欄位與 exact replay 測試方式。
- 依據來源：使用者於本輪提供的需求與限制；`rng/seeding.py`、`rng/strategy.py`、`machine/core.py`、`engine/models.py`、`tools/solver_config_loader.py`。

## 討論的演化

- D01：從「相同 seed 應完全一致」出發，經 worker 排程與時間停止反例後，形成 exact replay／traceable run 分級契約。

## 邊界與未解問題

- K1 的現行 task seed 不包含 solver ID 與 param-set index；是否維持跨 variant 共用 seed 尚未定案。
- solver 內部若引入平行化，RNG 消耗可能再次受到排程影響，需要獨立討論。
- 尚未建立 execution fingerprint schema 與自動化重現測試。
- 參考系統 K2 的 upstream `problab` 實作不在本輪指定路徑內；目前只採用 K2 專案接線與其內附文件，不把所有 upstream 細節視為已驗證事實。

## 知識範圍與前提

- K1｜`/home/sean/optiforge-optimization-solver`｜目前系統｜已參考・鎖定。
- K2｜`/home/sean/work/steak_math_v0510`｜參考 Slot 系統｜已參考・鎖定。
- 實際採用的 K1 來源集中於 `engine/`、`machine/`、`simulator/`、`experiment/`、`problem/`、`rng/`、`solver/`、`tools/`、`cli/` 與架構文件。
- 實際採用的 K2 來源集中於 `pkg/engine`、`internal/rng`、`cmd/run`、`cmd/opt`、`go.mod` 與 `plan/docs` 架構文件。
- LLM 背景知識已開啟，只用於一般軟體架構與確定性推論，不視為外部查證。
- 本文件區分專案程式事實、使用者設計要求與討論推論；未完成的議題保留為待處理問題。

## 交接資訊

- 可安全採用 D01 的停止條件分級，作為後續 RNG 設計的暫定基線。
- 不可假設不同硬體、時間停止或 solver 內部平行執行能產生完全相同的結果。
- 下一步由異端辯士挑戰 exact replay 契約的必要性與維護成本。

## 追加討論紀錄

### D02｜Exact replay 與統計可重現性的角色

- 討論時間：2026-09-13 09:42:39 +08:00
- 狀態：當時結論已確認
- 與既有結論的關係：補充並收縮 D01，不回寫 D01 的當時結論。
- 討論問題：研究型最佳化平台是否應把單次執行結果完全相同，視為最重要的可重現性保證。
- 初始主張：符合 execution fingerprint 且採固定迭代停止時，系統應提供 exact replay。
- 關鍵挑戰：隨機最佳化研究真正關心的是多個 seed 下的結果分布；鎖定單次結果可能增加環境維護成本，也不能證明算法品質可靠。
- 決策過程：接受 exact replay 不能代表研究結論可重現，也不應限制跨版本或跨硬體演進；但保留它作為同一 execution fingerprint 內定位 RNG、排程與程式回歸的工程契約，並將研究可信度交給獨立的統計可重現性契約。
- 結論：
  1. 可重現性分成兩個互補維度，不再以單一等級表達。
  2. Deterministic replay 用於除錯與 regression testing；在固定 execution fingerprint、固定工作量與相同 task seed 下，外層 worker 數不應改變單次結果。
  3. Statistical reproducibility 用於評估算法品質；必須比較多個 seed 的分布與彙總指標，單次 exact replay 不能替代它。
  4. execution fingerprint 改變後即進入新的重現範圍，不要求新舊環境產生完全相同結果，但必須能辨識兩者不可直接宣稱等價。
  5. `max_seconds` 執行只承諾可追溯與統計評估，不承諾 deterministic replay。
- 主張變化：`exact replay 是首要研究保證` → `exact replay 是受限的工程診斷契約` ＋ `統計可重現性是研究結論契約`。
- 適用邊界：本結論尚未定義統計指標、容許誤差或跨版本比較門檻，也尚未證明所有現行 solver 都能達成 deterministic replay。
- 待處理問題：驗證 NumPy／SciPy／Numba 與各 solver 的實際確定性；定義統計可重現性的 seed 數量、指標與接受標準；確定 execution fingerprint schema。
- 依據來源：使用者對可重現性與時間停止的要求；`rng/seeding.py`、`experiment/seed_bank.py`、`engine/models.py`、`machine/core.py`、`.github/workflows/ci.yml`；一般隨機實驗設計背景知識。

### D03｜論文投稿所需的實驗可重現性

- 討論時間：2026-09-13 09:46:24 +08:00
- 狀態：當時結論已確認；投稿規範的普遍性仍待外部查證
- 與既有結論的關係：修正 D02 對 exact replay 工程價值的表述，不回寫 D02；D02 所稱「不能單獨證明算法品質」仍保留。
- 討論問題：exact replay 是否只是除錯能力，或同時是論文實驗可重現性的一部分。
- 初始主張：D02 將 deterministic replay 主要定位為除錯與 regression testing，將統計可重現性定位為研究結論契約。
- 使用者修正：投稿論文通常要求實驗可被重現，因此「能重播」本身也是實驗系統的重要要求，不能只視為工程便利。
- 決策過程：接受論文需要可重現的實驗產物，但進一步區分「提供足夠材料重新執行」、「固定條件下重現單次結果」與「多 seed 下重現研究結論」；保留 exact replay 的論文價值，同時避免把單次相同結果誤當成算法穩健性的完整證明。
- 結論：
  1. Paper artifact reproducibility 是系統核心需求：應保存或提供程式版本、依賴、problem 資料、solver config、停止條件、seed 與執行命令，使投稿審查者能重新執行實驗。
  2. Deterministic replay 是 artifact reproducibility 的一部分：在相同 execution fingerprint 與固定工作量下，單次 run 應可得到相同結果，並可作為論文數值表與除錯的驗證工具。
  3. Statistical reproducibility 是另一項必要證據：隨機算法的研究主張仍須由多 seed 的分布與統計摘要支持。
  4. 三者是包含但不等價的需求；能重播單次結果很重要，但不能單獨證明算法品質或研究結論具有穩健性。
  5. `max_seconds` 實驗仍應完整保存 artifact 與 seed，但只能重現執行條件及統計結論，不承諾單次終點完全相同。
- 主張變化：`exact replay 主要是工程診斷契約` → `exact replay 同時是論文 artifact reproducibility 的重要組件，但不是研究穩健性的充分條件`。
- 適用邊界：這是本專案決定採用的投稿級設計要求；不同期刊、會議或 artifact badge 是否要求 bitwise-identical output 尚未查證，不宣稱所有投稿規範完全一致。
- 待處理問題：確認目標投稿場域的 reproducibility／artifact 規範；設計可攜的 run manifest；定義統計重現的指標與門檻。
- 依據來源：使用者對投稿需求的修正；K1 的 `readme.md`、`experiment/seed_bank.py`、`engine/models.py`、`tools/show.py`、`.github/workflows/ci.yml`；一般研究可重現性背景知識。

### D04｜外部投稿與 Artifact 標準對「完整還原」的要求

- 討論時間：2026-09-13 16:21:29 +08:00
- 狀態：外部查證完成；當時結論已確認
- 與既有結論的關係：以官方規範驗證並收緊 D03，不回寫 D03；否定「只要符合統計分布即可滿足投稿重現要求」這種過度寬鬆的解讀。
- 討論問題：主要電腦科學與最佳化投稿／artifact 規範，是否普遍要求完全還原實驗，以及是否要求跨硬體 bitwise-identical output。
- 初始主張：投稿可能只要求材料完整、主要結果可合理再現，不一定要求所有數值逐位元一致。
- 使用者修正：指導教授要求最好能完整還原；僅符合統計分布不足以作為本系統的實驗標準。
- 查證結果：
  1. NeurIPS 要求提供重現主要實驗結果所需的 code、data、instructions，並明示應包含 exact command 與 environment；同時另要求說明變異來源與統計顯著性。這表示「可執行地重建主要結果」與「統計證據」是並列要求，後者不能取代前者。
  2. INFORMS _Operations Research_ 期望作者提供所有 code、scripts、data 與足以讓他人重現論文結果的說明；_INFORMS Journal on Computing_ 對以計算實驗為主要貢獻的論文，把釋出軟體列為最終接受條件，並將 repository 與論文一同凍結。
  3. ACM PADS 的 artifact 評估要求 artifact documented、consistent、complete、exercisable；Results Reproduced 指主要結果由作者以外的人使用作者 artifact 成功取得。
  4. 但跨硬體逐位元相同不是一致的普遍門檻。ACM SIGMOD 明示：時間等結果受硬體影響，無相同硬體時不期待 identical results，而要求重建資料／圖表並支持相同核心行為與結論。
- 決策過程：官方規範支持使用者與指導教授對「完整材料、可實際重跑、能重建主要結果」的要求，因此不能把統計分布相符當成唯一驗收；另一方面，官方規範也沒有形成「任何硬體、任何停止條件皆須 bitwise identical」的共同要求。故將本專案的標準定得比最低投稿規範更強，但把保證範圍寫清楚。
- 結論：
  1. Optiforge 採用「完整還原優先」作為內部標準；僅有相近統計分布不算完成實驗重現。
  2. 論文主要數值實驗應使用固定工作量（如 `max_iterations`／固定 evaluations），並在相同 execution fingerprint 下要求 deterministic exact replay。
  3. 每次論文 run 必須保存不可變的 run manifest、程式 commit、problem/data hash、完整 solver config、base/task seeds、RNG 與 seed-derivation 版本、dependency lock/container、執行命令、raw per-run results，以及產生圖表與表格的腳本。
  4. 多 seed 統計分析仍然必要，用來證明算法結論穩健；它是 exact replay 之外的第二道要求，不能替代 exact replay。
  5. `max_seconds` 必須保留，但歸類為 performance/time-budget experiment：保存同等完整 artifact、硬體資訊、實際迭代／evaluation 數與多次重複統計，不宣稱單次終點 exact replay。
  6. 跨硬體重跑的驗收是能重建主要數據、圖表與結論；跨硬體 bitwise equality 不列為共同承諾。同硬體也只有在固定工作量及 execution fingerprint 一致時才承諾 exact replay。
- 主張變化：`材料完整且統計相近可能足夠` → `官方標準要求材料可執行並能重建主要結果` → `本專案採更嚴格的同 fingerprint／固定工作量 exact replay，同時保留跨硬體與時間停止的明確例外`。
- 適用邊界：這是跨 NeurIPS、ACM artifact/SIGMOD 與 INFORMS 最佳化期刊規範歸納出的工程基線；實際投稿時仍需再核對目標 venue 當年度規範。`exact` 的比較層級（完整 raw output、最佳解、軌跡或 bit pattern）尚待另題定義。
- 待處理問題：選定目標 venue 後建立 compliance checklist；定義 exact replay 的欄位級驗收；確認 NumPy／SciPy／Numba、浮點 reduction 與 solver 內部平行化對同 fingerprint replay 的限制。
- 外部來源：
  - [NeurIPS Paper Checklist Guidelines](https://neurips.cc/public/guides/PaperChecklist)
  - [ACM SIGMOD Availability & Reproducibility Initiative](https://reproducibility.sigmodconf.hosting.acm.org/)
  - [ACM SIGSIM PADS 2024 Reproducibility and Artifact Evaluation](https://sigsim.acm.org/conf/pads/2024/blog/artifact-evaluation/)
  - [INFORMS Journal on Computing Software Policy](https://pubsonline.informs.org/page/ijoc/softwarepolicy)
  - [INFORMS Operations Research Code and Data Disclosure Policy](https://pubsonline.informs.org/page/opre/code-and-data-disclosure-policy)

### D05｜停止模式的完整集合與混合模式語意

- 討論時間：2026-09-13 16:32:58 +08:00
- 狀態：當時結論已確認
- 與既有結論的關係：精確化 D01、D03、D04 對停止條件的分類；不回寫舊 block。另將 D04 所稱的結果分類標記移出結果資料，改由文件定義契約。
- 討論問題：系統應支援哪些停止模式；同時設定時間與迭代上限時，兩項限制如何組合；結果是否需要標示可否 exact replay。
- 初始主張：論文主要數值實驗優先使用固定迭代；時間停止保留但不保證 exact replay，並曾提議在結果中標記其分類。
- 使用者修正：三種模式都必須支援；結果資料不需要額外標記是否可重現，相關保證寫在文件；混合模式採任一上限先到即停止。
- 決策過程：先區分「支援的停止能力」與「建議用於 exact replay 的模式」，避免把論文建議誤寫成系統功能限制；再把混合條件定義為 OR，讓時間與迭代都保持上限語意；最後將重現性分類視為模式契約，而不是每筆結果的評價欄位。
- 結論：
  1. 系統支援 `iteration-only`、`time-only`、`time-or-iterations` 三種停止模式。
  2. `time-or-iterations` 採 OR 語意：時間上限或迭代上限任一先到即停止。
  3. 只有 `iteration-only` 可在 execution fingerprint 相同的前提下承諾 deterministic exact replay。
  4. `time-only` 與 `time-or-iterations` 都可能由時間決定 RNG 消耗量，因此模式契約不承諾 exact replay；即使某次混合執行實際由迭代上限先觸發，也不把整個模式提升為無條件可重現。
  5. 不在每筆結果加入 `reproducible` 或同類判斷欄位；各停止模式的重現保證由系統文件統一定義。
- 主張變化：`固定迭代是主要模式，時間模式另行分類` → `三種模式都是正式能力` → `混合模式明定為任一上限先到即停，重現性差異留在文件契約而非結果標籤`。
- 適用邊界：本結論只定義停止條件與模式級重現保證，不決定結果 schema 是否保存實際停止原因、實際迭代數或 elapsed time。
- 待處理問題：結果資料的最小必要欄位；一般文件、版本庫與 experiment-level manifest 各自應負責保存哪些重現資訊。
- 依據來源：使用者本輪確認；D01–D04 的既有討論與外部查證。

### D06｜實驗設定快照與同名實驗覆寫策略

- 討論時間：2026-09-13 16:37:36 +08:00
- 狀態：當時結論已確認；失敗時的替換原子性尚待討論
- 與既有結論的關係：收縮 D04「每次 run 保存完整 manifest」的要求，延續 D05 對結果資料精簡化的方向；不回寫舊 block。
- 討論問題：一般文件能否取代單次實驗設定快照，以及相同實驗重新執行時是否保留設定歷史。
- 初始主張：每筆結果不應重複保存 commit、dependency、RNG 等共同資訊，這些資訊可放在文件或版本庫中。
- 關鍵挑戰：一般文件只能描述系統，不能唯一指出某批結果當時使用的 problem、solver、參數、停止條件與 seed；只靠輸出也無法反推出唯一實驗輸入。
- 決策過程：將資訊拆成研究版本、實驗與單次結果三層；研究版本共同負責程式、文件、依賴鎖定與 RNG 實作，實驗層只保存一次原始設定，結果層保持精簡。使用者確認相同實驗重跑時採覆寫而非在結果目錄維護歷史版本。
- 結論：
  1. 系統應將該次使用的原始 `experiment.yaml` 自動保存到實驗結果目錄，作為整場實驗唯一的設定快照；不在每筆 run 重複。
  2. 研究版本中的文件負責說明 RNG、停止模式與重現性契約；Git commit 與 dependency lock 負責版本級資訊。
  3. 同名實驗重新執行且設定已改變時，新的設定快照覆蓋舊設定；實驗結果目錄內不保留設定歷史。
  4. 因此實驗結果目錄的語意是「同名實驗的最新一次執行」，不是版本庫或不可變 archive。
  5. 現行 `Experiment.run()` 會在執行開始前刪除整個同名實驗目錄，與「不保留舊版」方向一致，但尚未保存原始 `experiment.yaml`。
- 主張變化：`共同資訊全部放一般文件` → `一般文件無法識別特定實驗` → `每場實驗保存一次原始設定，但同名重跑直接覆寫且不留歷史`。
- 適用邊界：本結論不要求在 live result directory 內保留歷史；正式論文 artifact 是否另行凍結，由後續發布流程決定。
- 待處理問題：重跑時是否整個結果目錄一起替換；執行中斷時保留舊的完整結果還是留下空／部分目錄；如何避免新設定與舊結果混合。
- 依據來源：使用者本輪確認；`experiment/experiment.py` 的結果目錄重設流程；D03–D05 的既有討論。

### D07｜同名實驗重跑失敗時的舊結果保護

- 討論時間：2026-09-13 16:41:17 +08:00
- 狀態：需求結論已確認；發布替換機制尚待確認
- 與既有結論的關係：為 D06 的覆寫策略增加失敗安全邊界；不回寫 D06。
- 討論問題：同名實驗重新執行但未能完整產出結果時，舊的完整結果應被刪除還是保留。
- 初始主張：D06 定義同名重跑會覆蓋舊設定且不保留歷史；現行 `Experiment.run()` 在新執行開始前直接刪除舊目錄。
- 使用者修正：只有新實驗能完整產出時才可替換舊實驗；新實驗過程若發生任何意外，舊版實驗結果必須保持不變。
- 決策過程：將「是否保留歷史版本」與「替換失敗時是否保護目前版本」分開。正常完成後仍只留新版，不形成版本歷史；但新結果尚未完成前不得破壞舊的完整結果。
- 結論：
  1. 新實驗的設定、run results、summary 與 seed bank 必須先寫到正式結果目錄之外的 staging directory。
  2. 新實驗全部完成並通過完整性檢查以前，既有同名實驗目錄保持不變。
  3. 新實驗在計算、寫檔或驗證階段失敗時，刪除或隔離 staging 資料，舊結果繼續作為正式結果。
  4. 新實驗成功發布後只保留新版正式結果；結果目錄內仍不維護歷史版本。
  5. 現行「執行開始前 `shutil.rmtree(experiment_output_dir)`」不符合這項失敗保護需求，後續實作必須調整。
- 主張變化：`同名重跑直接覆寫且不留歷史` → `不留歷史，但只在新版完整可用後才替換；失敗時舊版保持不變`。
- 適用邊界：需求已確認，但「先刪舊目錄再移入新版」仍存在刪除與搬移之間的崩潰窗口，尚未視為已確認的安全實作。
- 待處理問題：採用可恢復的 backup-rename 流程、版本目錄加原子 current pointer，或限定平台後使用目錄交換；同時需定義完整性檢查與啟動時的殘留 staging 復原規則。
- 依據來源：使用者本輪確認；`experiment/experiment.py:58-61`；D06 的既有討論。

### D08｜現行結果落地粒度與簡化替換方向

- 討論時間：2026-09-13 17:06:27 +08:00
- 狀態：現況已確認；最終快取／落地策略尚待決定
- 與既有結論的關係：補充 D07 的程式現況；使用者否決 D07 待處理項目中的 backup-rename／複雜交換方向，但不回寫 D07。
- 討論問題：現行實驗是每完成一題就落地結果，還是將整場資料全部快取後才輸出；這會如何影響「新版成功前保留舊版」的簡單作法。
- 使用者立場：不採 staging、backup rename 等搬移與復原機制；保留簡單作法，在新資料成功產出後才清空舊資料並寫入新版。
- 程式查核：
  1. `Experiment.run()` 目前在任何計算開始前刪除整個同名實驗目錄。
  2. `_run_dataset()` 依序處理各個 problem。
  3. `_run_problem()` 只在記憶體累積當前 problem 的 accepted rows；problem 收集完成後，立即呼叫 `write_simulator_result()`。
  4. `write_simulator_result()` 依 solver／param variant 立即寫出 `runs.csv`、`runs.json`、`summary.json` 與 `summary.csv`。
  5. 全部 problem 完成後，才在實驗根目錄寫出整場 `summary.json` 與 `seed_bank.json`。
- 結論：現行流程是「當前 problem 暫存在記憶體，problem 完成即落地」的混合模式，不是每個 task 立即落地，也不是整場實驗完成後一次輸出。若後續 problem 失敗，先前 problem 的新版部分結果會留在磁碟，但舊實驗已在開跑前被刪除，因此不符合 D07 的舊結果保護需求。
- 主張變化：`考慮 staging＋可恢復交換` → `使用者要求保留簡單替換` → `確認現行逐 problem 落地與簡單的整場延後替換存在結構衝突`。
- 適用邊界：本 block 只確認目前落地時機及使用者的簡化方向，尚未決定要改成整場記憶體快取，還是允許最小限度的暫存輸出。
- 待處理問題：若不使用 staging，是否接受整場結果留在記憶體直到所有 problem 完成；若輸出檔本身寫入失敗，是否接受舊目錄已被清除而無法恢復。
- 依據來源：使用者本輪修正；`experiment/experiment.py` 的 `run()`、`_run_dataset()`、`_run_problem()`；`tools/show.py` 的 `write_simulator_result()`。

### D09｜斷點續跑的必要粒度

- 討論時間：2026-09-15 12:30:06 +08:00
- 狀態：需求已確認；持久化載體與 checkpoint schema 尚待討論
- 與既有結論的關係：擴充 D07、D08；新實驗失敗時不只要保護舊正式結果，也要保留本次新實驗已完成的工作，供下次續跑。這使「整場只存記憶體、失敗後全部重跑」不再符合需求，但不回寫舊 block。
- 討論問題：新實驗意外中止後，是否只需保留舊正式結果，或還必須從本次新實驗已完成的位置繼續。
- 初始主張：若允許失敗後整場重跑，可不導入資料庫；若要求斷點續跑，則需要某種持久化 checkpoint，SQLite 只是候選而非必然選擇。
- 使用者確認：系統需要同時支援從已完成的 problem 接續，以及從 problem 內已完成的 repeat 接續；是否使用 SQLite 另行比較後決定。
- 決策過程：先區分「保護上一版正式結果」與「保存本次未完成執行的進度」。前者只要求延後覆寫正式結果；後者要求跨程序中止仍存在的工作狀態，因此不能只靠記憶體。再將恢復粒度限定於已持久化完成的 problem／repeat 邊界，而非假定能從 solver 任意指令或單次求解內部狀態恢復。
- 結論：
  1. 新實驗必須在每個 problem 完成時留下可驗證、可供續跑的持久化 checkpoint。
  2. 同一 problem 內，每個已完成 repeat 也必須留下足以避免重算該 repeat 的持久化進度與結果。
  3. 恢復位置是最後一個完整且通過一致性檢查的 checkpoint；不承諾從寫入一半的 repeat 或 solver 內部迭代狀態恢復。
  4. 新實驗尚未全部成功以前，D07 所定義的上一版正式結果仍須保持可用；未完成新實驗的 checkpoint 與正式結果必須在語意上分離。
  5. SQLite、append-only journal、獨立 checkpoint 檔案等都可作為候選載體；本 block 不預先指定 SQLite。
- 主張變化：`若不需續跑，可用整場記憶體暫存而不使用資料庫` → `problem 級與 repeat 級續跑均為正式需求，因此必須有持久化 checkpoint，但資料庫選型仍開放`。
- 適用邊界：尚未定義「repeat 完成」是一次嘗試、一次 accepted result，或某個 solver／parameter variant 的完成單位；也尚未決定失敗 checkpoint 的保留期限、設定變更後能否沿用，以及同名實驗如何辨識可續跑的 execution identity。
- 待處理問題：檢查 `problab_dev` 是否有可借用的儲存／恢復設計；比較 SQLite、檔案式 checkpoint 與其他方案；定義 checkpoint key、提交粒度、完整性檢查、設定相容性及正式結果發布流程。
- 依據來源：使用者本輪明確確認；D07、D08 的既有討論；一般持久化 checkpoint 與故障恢復背景知識。

### D10｜更正斷點續跑的目標流程：單純算法模擬而非條件式收集

- 討論時間：2026-09-15 13:44:10 +08:00
- 狀態：範圍錯誤已確認並更正；模擬 checkpoint 載體尚待討論
- 與既有結論的關係：不回寫 D08、D09。D08 查到的行為確實存在，但只屬於 `cli.exp → Experiment` 的條件式收集流程，不能回答目前的單純模擬問題。D09 的 problem／repeat 級持久化需求仍成立，但其中 accepted／rejected、evaluator 與收集狀態不屬於目前範圍。D01–D05 的 task seed 與停止條件結論仍適用；D06、D07 的設定覆寫與舊正式結果保護仍是需求，但後續必須改以模擬流程重新映射實作。
- 討論問題：先前 checkpoint 討論是否混淆了「單純執行算法的模擬流程」與「根據條件挑選 seed／結果的優化器或收集流程」，以致方案方向錯誤。
- 使用者修正：目前只討論單純算法模擬；優化器是另一條依條件收集符合期望 seed 與結果的流程，不應把它的 evaluator／accepted repeat 套入模擬 checkpoint。
- 程式查核：
  1. 單純模擬入口是 `cli.run`；它建立 `SimulationBundle`，依 worker 數呼叫 `Simulator.run_sequential()` 或 `run_batch()`，取得完整 `SimulatorResult` 後才呼叫 `write_simulator_result()`。
  2. `Simulator` 將 problem × repeat × solver／parameter variant 展開成 `RunTask`；單純模擬沒有 evaluator，也沒有 accepted／rejected 或 `collects`。
  3. 平行 `MachinePool` 會在 worker 完成時把 `SolveResult` 放進記憶體字典；必須等所有 tasks 完成後，才依原 task 順序驗證並組成 `MachineResult`。中途完成的 task 目前不會持久化。
  4. `cli.exp → Experiment` 才具有 evaluator、`collects`、accepted／rejected repeat 與逐 problem 輸出；前面針對 evaluator 狀態的攻防因此偏離本題。
- 結論：
  1. 後續 checkpoint／資料庫選型只針對 `cli.run → Simulator → MachinePool` 的單純算法模擬流程。
  2. 模擬中的每個排定 `RunTask` 都是正式工作，不經 evaluator 篩選；checkpoint 不需要保存 accepted／rejected 或 evaluator 狀態。
  3. repeat 級續跑應以完整 task identity（problem type、dataset、problem、solver、parameter variant、repeat index）辨識已完成工作；problem 級續跑則是該 problem 所需 tasks 已全部完成的衍生狀態。
  4. 現行單純模擬會將整批結果留在記憶體，全部完成後才統一寫檔，因此目前不支援 problem 或 repeat 級斷點續跑。
  5. K3 `problab_dev` 的條件式 seed collection 不作為模擬流程模型；只能選擇性借用 pending／正式結果分離、schema version、hash 驗證等通用持久化原則。
- 主張變化：`以 Experiment 的 accepted repeat 作為 checkpoint 單位` → `確認該流程屬於條件式收集，不是本題` → `改以 Simulator 的每個完整 RunTask 作為最小 checkpoint 單位`。
- 適用邊界：本結論不設計優化器／條件式收集的 resume，也不要求保存 evaluator 狀態；尚未決定多個平行 tasks 完成順序如何提交、結果保存完整 `SolveResult` 或輸出用 `ResultEntry`，以及使用 SQLite 或檔案。
- 待處理問題：比較單一 writer SQLite、逐 task 原子檔案與 append-only journal；定義 task 完成的交易邊界；決定 checkpoint 是否保存 `best_solution`；設計成功後的正式結果輸出與舊結果替換。
- 依據來源：使用者本輪範圍更正；`cli/run/main.py`、`cli/run/support.py`、`simulator/core.py`、`machine/core.py`、`engine/models.py`；D08、D09 的既有討論。

### D11｜續跑需求擴展至單一 task 內部

- 討論時間：2026-09-15 14:00:55 +08:00
- 狀態：需求已確認；solver checkpoint 契約與支援策略尚待討論
- 與既有結論的關係：擴充 D09、D10，不回寫舊 block。problem／repeat 邊界的持久化仍需要，但只保存已完成 `RunTask` 已不足以滿足長任務的效率要求。
- 討論問題：若單一 task 可能執行一小時或更久，中斷後從頭重跑該 task 是否可以接受。
- 初始主張：通用 task-level checkpoint 保存所有已完成 tasks；中斷當下尚未完成的 task 從頭重跑。solver 內部 checkpoint 因需要保存演算法狀態，可另列為個別 solver 的選配能力。
- 使用者修正：不能接受長時間 task 在中斷後從頭重跑；系統應能從 task 內最近一次有效進度繼續，以避免大量計算浪費。
- 決策過程：區分「保存已完成 task」與「保存執行中 task」兩級恢復。前者只需保存完整 `RunTask` 結果；後者必須由 solver 暴露可序列化的執行狀態，並按固定策略週期性提交。恢復點仍是最後一個完整 checkpoint，不是中斷的精確 CPU 指令位置。
- 結論：
  1. 單純模擬除了 problem／repeat 級續跑，也必須支援單一長 task 內部續跑。
  2. 執行中 task 應定期產生 solver checkpoint；意外中止後從最後一個完整 checkpoint 恢復，只重算該 checkpoint 之後的工作。
  3. checkpoint 至少需要描述演算法進度、RNG 狀態、目前最佳結果，以及足以繼續計算的 solver-specific state；實際 schema 尚未決定。
  4. 固定時間與時間加迭代上限的模式還必須保存已消耗的有效執行時間，否則恢復後會重新取得完整時間預算；詳細時間語意另題決定。
  5. 是否要求所有 solver 強制支援內部 checkpoint，或以 capability 宣告支援，尚未決定。
- 主張變化：`中斷中的 task 可從頭重跑，solver 內部 resume 為選配` → `長 task 從頭重跑不可接受，task 內部 resume 成為正式系統需求`。
- 適用邊界：不承諾從任意指令位置恢復；未完成 checkpoint 本身可以捨棄。尚未決定 checkpoint 頻率、儲存載體、版本相容策略，以及不同 solver state 的編碼方式。
- 待處理問題：盤點現有 solver 執行介面與可序列化狀態；決定 checkpoint capability 是否強制；定義 snapshot／restore protocol、時間預算續算規則、寫入責任與失敗一致性；之後再比較 SQLite 與檔案載體。
- 依據來源：使用者本輪明確要求；D09、D10 的既有討論；一般故障恢復與迭代式最佳化演算法背景知識。

### D12｜專案同時追求算法貢獻與系統貢獻

- 討論時間：2026-09-15 15:25:27 +08:00
- 狀態：目標已確認；底層系統的獨特價值與可驗證貢獻尚待形成
- 與既有結論的關係：將 D11 的 checkpoint 設計暫停在能力策略尚未決定的位置，先處理更上游的專案定位；不回寫舊 block。
- 討論問題：在 Optuna、Ray Tune、pymoo、DEAP、Nevergrad、SMAC3、Ax 等既有系統已涵蓋大量功能後，OptiForge 是否仍值得自行開發；專案最後應以新算法還是系統本身作為主要貢獻。
- 初始主張：若 OptiForge 只是另一套通用優化框架，差異與投入理由不足；若它是服務自研組合最佳化算法與可重現論文實驗的專用執行核心，則具有內部工程價值，但尚不能因此直接宣稱學術系統貢獻。
- 使用者確認：算法貢獻與系統貢獻兩者都重要，目標是同時具備；目前真正的不確定點是底層系統相對既有工具的價值與貢獻究竟在哪裡，必要時應重新尋找與定義。
- 決策過程：先區分「對自身研究有用的工程基礎設施」與「對研究社群成立的新系統貢獻」。前者可由統一 problem／solver、seed、repeat、停止條件與結果契約成立；後者還必須證明既有系統存在具體缺口，且本系統提出可驗證的新能力、保證、抽象或效能結果。因此目前不能以已完成整合工作直接推出系統具有研究新穎性。
- 結論：
  1. OptiForge 的目標明確包含算法與底層系統兩類貢獻，不採二選一定位。
  2. 現有 problem／solver registry、可重現 seed 契約、平行模擬與結果流程可以證明工程用途，但尚不足以單獨證明系統研究貢獻。
  3. 後續必須重新建立一個可被反駁的系統價值主張，指出目標使用者、既有方案無法妥善處理的問題、OptiForge 的新機制，以及能驗證改善的指標。
  4. 在價值主張形成以前，不因已投入開發成本而預設整套底層架構都應保留，也不先把 checkpoint、資料庫或分散式能力視為貢獻本身。
- 主張變化：`新算法與專用實驗工具可能足以支撐專案` → `使用者要求算法與系統都形成貢獻` → `必須另行證明底層系統的獨特問題、機制與成效，工程用途不能代替研究貢獻`。
- 適用邊界：本 block 只確認雙重貢獻目標與重新定位的必要性，尚未判定 OptiForge 已具備系統新穎性，也未決定應保留、自建或改用哪些外部元件。
- 待處理問題：形成候選系統價值假說；逐項比較既有系統能否以合理成本滿足；選定可量化的系統貢獻；再回頭判斷 checkpoint 等功能應是核心機制、支援功能或外部整合。
- 依據來源：使用者本輪確認；K1 現有專案；神諭使者對 Optuna、Ray Tune、pymoo、DEAP、Nevergrad、SMAC3、Ax 與 Submitit 的外部查證。

### D13｜系統改以工程價值評估，不以研究新穎性為門檻

- 討論時間：2026-09-15 15:43:15 +08:00
- 狀態：評估準則已由使用者確認；OptiForge 的工程價值是否足以支撐獨立維護仍待具體替代性比較。
- 與既有結論的關係：更正 D12 將底層系統同時置於「研究貢獻」評估的方向；不回寫 D12，保留立場變化。後續對算法可討論研究貢獻，對系統則以實際工程效益為判準。
- 討論問題：既有系統若能提供相同或更強能力，OptiForge 是否還具有足夠的工程價值。
- 使用者修正：Solver/problem registry、YAML、平行 worker、checkpoint、seed、CLI 等可以是工程貢獻；不應因為它們不構成系統研究新穎性，就推論它們沒有系統價值。
- 外部查核：
  1. IOHExperimenter 已直接提供 algorithm、problem/instance/dimension、repetitions、平行 jobs、logging 與 custom problem，與 OptiForge 的基本實驗矩陣高度重疊。
  2. COCO 提供 benchmark suite、observer/output、可分批並行化的實驗範本與後處理；jMetalPy 提供可擴充 problem/algorithm、多次 experiment jobs、結果匯總及多種平行 evaluator。
  3. pymoo 可將整個 algorithm object 序列化後從 checkpoint 續跑，並支援 custom problem 與多種平行方式。
  4. Ray Tune 的 custom Trainable、trial/experiment checkpoint、失敗重試、本地／集群調度與持久化儲存，已能組合出 problem/repeat 層與 task 內部續跑，而且通用容錯與分散式能力明顯比現行 OptiForge 成熟。
  5. 這些工具不會自動提供 OptiForge 特定的 task identity、solver/problem 相容規則、seed 派生及結果 schema；但這些差異可用薄層 adapter 實作，所以「別人沒有開箱即用」不足以單獨證明應自建底層引擎。
- 程式現況：OptiForge 已有 task-derived seed、worker 數／solver 順序無關的 seed 測試、solver/problem 登錄與相容驗證、shared-memory process pool、標準結果與 seed-bank replay；但 `cli.run` 尚未將完成 task 持久化，也沒有 solver 內部 checkpoint/restore 契約。
- 當前結論：
  1. 「其他系統也能做到大部分，且在通用調度、持久化與容錯上比 OptiForge 更好」屬實；撤回將「平行無關／中斷無關重現」當作 OptiForge 獨有能力的說法。
  2. 功能重疊不等於沒有工程價值；若一個專用工具能穩定降低本實驗室新增 solver/problem、避免實驗設定錯誤、重播論文實驗與維護自研算法的成本，仍可有充分的內部工程價值。
  3. 目前只能判定 OptiForge 是「已有實際用途的專用原型」，尚不能判定它已具備足以支撐獨立底層平台的工程價值。
  4. 是否值得繼續自建，必須用一個具體替代方案做成本比較：以「Ray Tune 處理調度／恢復＋OptiForge 薄層負責領域契約」為強基線，比較自建與整合的實作量、使用複雜度、依賴成本、故障恢復正確性及後續維護量。
- 主張變化：`系統功能必須證明研究新穎性` → `系統只需證明足夠的工程價值` → `既有系統功能重疊屬實，但是否應自建必須用薄層整合方案做可替代性驗證`。
- 適用邊界：本 block 評估的是實驗執行系統的工程價值，不否定自研最佳化算法的研究貢獻；也不因引入 Ray 就預設必須刪除現有架構。
- 待處理問題：對一個真實 MKP solver 與一組 problem/repeat 做 Ray 薄層替代性設計，估算要替換的程式邊界與仍必須保留的 OptiForge 領域邏輯。
- 外部來源：
  - [Ray Tune FAQ：分散式重現性與平行非決定性](https://docs.ray.io/en/latest/tune/faq.html)
  - [Ray Tune 持久化儲存與實驗／trial 恢復](https://docs.ray.io/en/latest/tune/tutorials/tune-storage.html)
  - [Ray Tune Trainable checkpoint 契約](https://docs.ray.io/en/latest/tune/api/doc/ray.tune.Trainable.html)
  - [IOHExperimenter Experiment API](https://iohprofiler.github.io/IOHexperimenter/api/ioh.Experiment.html)
  - [COCO 實驗介面](https://numbbo.github.io/coco-doc/C/)
  - [jMetalPy Experiments](https://jmetal.github.io/jMetalPy/tutorials/experiment.html)
  - [jMetalPy 平行與分散式 evaluator](https://jmetal.github.io/jMetalPy/tutorials/evaluator.html)
  - [pymoo Checkpoints](https://pymoo.org/misc/checkpoint.html)
  - [pymoo Parallelization](https://pymoo.org/parallelization/index.html)
  - [Optuna FAQ：平行模式的內在非決定性](https://optuna.readthedocs.io/en/stable/faq.html)

### D14｜專案方向改為需求先行，再決定自建、採用或混合

- 討論時間：2026-09-15 16:08:52 +08:00
- 狀態：方向調整已由使用者確認；具體需求與技術方案尚待逐項形成。
- 與既有結論的關係：延續 D13 的可替代性問題，但不直接從 Ray 或任一既有工具開始設計；先回到使用者、工作流與必要保證，再讓需求決定架構。
- 討論問題：OptiForge 真正要解決的工程問題是什麼，及這些需求應由自建系統、既有工具或混合架構承擔。
- 使用者立場：若不先重新釐清需求，即使完成現有底層系統，也可能只是重複造輪子，缺乏足夠意義。
- 決策過程：前一輪已確認多個成熟系統能覆蓋 OptiForge 的大部分通用功能，因此不能再以「現有程式有什麼」反向定義需求。先定義必須解決的實驗痛點與不可妥協保證，才能公平比較 build、adopt 與 hybrid，並避免沉沒成本左右方向。
- 結論：
  1. 暫不預設現有 OptiForge 底層架構必須全部保留或完成。
  2. 先建立與工具無關的需求清單，包含目標使用者、核心工作流、現在會發生的失敗／成本、不可妥協保證與可接受取捨。
  3. 需求確認後，才對每項能力比較三種方案：完全自建、直接採用成熟系統、保留 OptiForge 領域層但復用外部基礎設施。
  4. 方案判準是實際工程成本與風險，不是功能是否由自己寫；至少要比較實作量、使用者操作成本、依賴／部署成本、正確性、可維護性與日後擴充。
- 主張變化：`先找出 OptiForge 相對於其他系統的獨特功能` → `不以獨特為目標，先釐清真實需求` → `用需求與工程成本決定自建、採用或混合`。
- 適用邊界：本 block 只確認決策方法與順序，尚未認定 Ray Tune、IOHExperimenter、pymoo 或現行 OptiForge 是最終方案。
- 待處理問題：從目標使用者與一次完整實驗工作流開始，找出沒有 OptiForge 時會重複發生、且值得由系統解決的高成本問題。
- 依據來源：使用者本輪明確提出的方向調整；D13 對現有系統功能重疊與可替代性的查核。

### D15｜需求起源：頻繁迭代下的可信比較與變體維護

- 討論時間：2026-09-15 16:20:21 +08:00
- 狀態：需求起源已確認；系統應如何支援這個流程尚待討論。
- 與既有結論的關係：將 D14 的「需求先行」收旂到第一個具體使用情境；尚不對應任何特定工具或架構。
- 討論問題：在沒有 OptiForge 時，哪一件反覆發生、高成本或容易出錯的工作，使單純實驗腳本不足以應付。
- 使用者經驗：核心循環是修改算法，然後執行長時間實驗判斷結果是否改善；必須固定 seed，否則無法區分差異來自演算法修改或隨機波動。日常還會頻繁調整算法參數與 problem model，嘗試數量增加後容易出現版本與組合維護困難。
- 結論：
  1. 第一個核心需求不是「提供一個求解器」，而是支援自研算法的頻繁變更—執行—比較循環。
  2. 比較必須控制 seed 等實驗條件，讓使用者能區分演算法效果與隨機波動。
  3. 系統需要管理的變化軸至少包含算法實作、算法參數、problem model 與 seed；當這些軸同時迭代時，需避免各種嘗試成為難以追蹤的腳本與版本分支。
  4. 實驗等待時間長會放大任何設定、版本或執行錯誤的成本，但「如何縮短等待或避免重算」屬於後續機制設計。
- 主張變化：`可能需要一套通用的最佳化實驗系統` → `先解決自研算法頻繁迭代時，長時間實驗難以可信比較與維護多種變體的問題`。
- 適用邊界：本 block 只記錄問題起源，尚未認定 checkpoint、registry、資料庫、Ray 或 OptiForge 現有架構是必要解法。
- 待處理問題：定義一次「改算法後做可信比較」的完整機制，特別是系統應記得哪些版本／設定並如何判定兩次執行可公平比較。
- 依據來源：使用者本輪描述的實際工作流。

### D16｜產品目標定位為「算法研發工作台」

- 討論時間：2026-09-15 16:34:51 +08:00
- 狀態：目標層級已由使用者確認；「工作台」的具體交互流程、變體模型與自動化邊界尚待定義。
- 與既有結論的關係：收旂 D14 的產品方向與 D15 的需求起源。OptiForge 不只做單次模擬或批次調度，而是支援長期、頻繁的算法研發循環；尚不因此預設底層必須自建。
- 討論問題：系統只應是批次執行器、可重現實驗管理器，還是更完整的算法研發工作台。
- 候選層級：
  1. 批次執行器：接受 solver、problem、參數與 seed，負責平行執行與輸出。
  2. 可重現實驗管理器：在批次執行之上，追蹤實驗設定、維持公平比較、支援中斷續跑並整理比較結果。
  3. 算法研發工作台：再管理算法、參數與 problem model 的多個變體，建立比較實驗，並整理統計與報表。
- 使用者選擇：系統應達到第三層「算法研發工作台」。
- 結論：
  1. OptiForge 的產品終點是算法研發工作台，不是單純的 solver runner。
  2. 批次執行與可重現實驗管理仍是必要能力，但它們是工作台內部的基礎層。
  3. 最終架構必須從「如何降低算法研發循環的管理與判斷成本」評估，而非只以任務能否平行執行為準。
- 主張變化：`建立一套可重現、可平行的模擬底層` → `以模擬與實驗管理為基礎，建立管理變體、比較與報表的算法研發工作台`。
- 適用邊界：「工作台」是產品能力邊界，不等於所有能力都要在單一程式或單一 UI 內自建；仍可以組合 Git、Ray、資料庫或其他外部元件。
- 待處理問題：定義算法實作、算法參數、problem model、dataset 與 seed 在工作台中的版本／變體身分，以及使用者如何建立並判讀一次比較。
- 依據來源：使用者本輪選擇；D14、D15。

### D17｜工作台必須管理多類研發變體

- 討論時間：2026-09-15 16:37:46 +08:00
- 狀態：變體管理範圍已由使用者確認；版本的儲存責任與身分機制尚待定義。
- 與既有結論的關係：將 D16 的「算法研發工作台」具體化為多類變體管理；不改變 D06 對同名實驗輸出目錄不保留歷史的舊結論，實驗輸出版本與研發變體是不同議題。
- 討論問題：修改算法後，工作台應只執行當前版本，還是應管理多個可用於比較的研發變體。
- 使用者選擇：工作台應管理多個算法實作、算法參數與 problem model 版本。
- 結論：
  1. 算法實作版本、算法參數版本與 problem model 版本都是工作台必須能辨識的研發變體。
  2. 工作台不能只假設檔案系統中的當前程式與當前 YAML 就是唯一可執行狀態。
  3. 後續的實驗定義必須能明確指向所選的算法、參數與 problem model 變體，才能管理與比較多種嘗試。
- 主張變化：`工作台支援建立算法比較` → `工作台還必須將算法實作、參數與 problem model 的多個版本納入可辨識、可指定的管理範圍`。
- 適用邊界：本 block 尚未決定工作台要自行保存每個版本的完整內容，或只紀錄 Git commit、設定檔路徑與 hash 等外部參照。
- 待處理問題：定義各類變體的 source of truth、不可變身分、命名方式、可組合關係與實驗引用方式。
- 依據來源：使用者本輪選擇；D15、D16。

### D18｜舊研發版本必須以完整快照直接重跑

- 討論時間：2026-09-15 16:40:00 +08:00
- 狀態：舊版本的使用體驗已由使用者確認；快照的完整內容與環境邊界尚待定義。
- 與既有結論的關係：回答 D17 所留的版本儲存責任。工作台不只保存外部參照後要求使用者手動還原，而是必須保存可直接執行的完整快照。這與 D06 的「同名實驗正式結果不保留舊版」是不同層次：本題管理的是可重跑的研發版本。
- 討論問題：未來重跑三個月前的舊版本時，由使用者手動切換各項版本，還是由工作台保存並直接執行當時快照。
- 使用者選擇：工作台保存完整快照，並能直接執行舊版本。
- 結論：
  1. 每個需要長期保留的算法實作／參數／problem model 版本，必須有不隨當前工作區修改的不可變快照。
  2. 使用者從工作台選擇舊版本後，不應還要手動 checkout 程式、還原 YAML 或拼裝 problem model 才能執行。
  3. 快照必須以「是否足以成功組裝並啟動該版本」驗證，不能只保存版本名稱或說明文字。
- 主張變化：`工作台只需辨識多個研發變體` → `研發變體必須保存為工作台可直接執行的完整快照`。
- 適用邊界：「完整」目前只表示可直接重跑，尚未確認是否必須包含 dataset 實體、Python／系統依賴、已編譯檔、container image 或硬體描述；也尚未決定用 Git、artifact store、container registry 或其他技術實作。
- 待處理問題：定義「直接執行」要在當前環境相容、可自動重建軟體環境，還是可放到其他裝置後仍能執行的層級。
- 依據來源：使用者本輪選擇；D06、D17。

### D19｜可執行快照的環境邊界限於同一裝置

- 討論時間：2026-09-15 16:41:33 +08:00
- 狀態：快照的執行環境邊界已由使用者確認；快照的建立時機尚待定義。
- 與既有結論的關係：收旂 D18 對「完整快照」的廣泛定義。快照必須在原裝置上可直接重跑，但不擴大為自動重建依賴或跨裝置部署的保證。
- 討論問題：舊版本「可直接執行」應限定於當前裝置，還是必須可自動重建軟體環境或跨裝置部署。
- 使用者選擇：只要保證在同一台裝置可直接執行。
- 結論：
  1. 快照至少要保存算法實作、算法參數、problem model 以及執行時必要的工作台設定，使它不受當前工作區後續修改影響。
  2. 快照可沿用原裝置現有的 Python、套件、系統 library、compiler 與硬體環境；工作台不承諾自動建立這些環境。
  3. 不要求產生 container image，也不把跨裝置可部署性納入當前工作台核心需求。
  4. 若原裝置的依賴環境未來發生不相容變更，快照不保證單獨解決；這是本輪刻意接受的取捨。
- 主張變化：`完整快照應可直接重跑` → `完整快照只需在原裝置與其現有環境中直接重跑`。
- 適用邊界：這是工作台的日常研發使用邊界；正式論文 artifact 未來仍可另行凍結 dependency lock 或 container，但不屬本需求的必備能力。
- 待處理問題：定義快照的建立時機、保存範圍、去重複方式與失效時的錯誤訊息。
- 依據來源：使用者本輪選擇；D18。

### D20｜既有框架通常保存 run 狀態，可執行版本另交由實驗追蹤與版本工具

- 討論時間：2026-09-15 16:59:20 +08:00
- 狀態：外部查證已完成；OptiForge 應採每次自動、手動建版或兩階段策略尚待使用者確認。
- 與既有結論的關係：回答 D19 後續的快照建立時機問題，並為 D18 的完整可執行快照提供外部實作參考；本 block 不直接選定產品策略。
- 討論問題：其他最佳化算法框架是否會為每次實驗保存可直接重跑的完整程式快照，及它們如何處理版本。
- 外部查核：
  1. Ray Tune 保存 experiment state 與 trial checkpoints，但 `Tuner.restore()` 要求呼叫端再提供與原實驗相同的 Trainable，且不支援在恢復時任意更改 search space。Ray 並未把該 Trainable 的整套原始碼自動凍結成研發版本。
  2. Optuna 的 RDB 保存 study/trial 狀態、參數與結果，但連 sampler/pruner 實例狀態都不自動保存；Artifact API 可關聯大型檔案，但上傳哪些檔案仍由使用者決定。
  3. IOHExperimenter 保存 algorithm name/info、實驗與 run attributes 及 benchmark 結果；jMetalPy 保存各 algorithm/problem/run 的 FUN、VAR、TIME 與統計輸出，兩者的公開實驗 API 都不會自動保存完整算法原始碼。
  4. SMAC3 保存 scenario、configuration space、runhistory、intensifier 與 optimization stats；這是最佳化過程的狀態，不是目標函數／算法實作的原始碼版本。
  5. Hydra 每次 run 自動建立輸出目錄並保存 YAML 設定，但不自動凍結應用程式原始碼。
  6. Sacred 是較接近 D18 需求的反例：它會自動發現實驗使用的 Python source files，在每次 run 由 observer 儲存原始碼副本，並紀錄設定、package dependencies、Git commit/dirty state、host 與受管理的 resources。
  7. MLflow 的典型作法是每次 run 紀錄 parameters、metrics、artifacts 與 Git commit；MLflow Projects 可直接執行指定 Git commit。這是使用 Git 作為程式 source of truth，而不是由最佳化引擎本身重做版本控制。
- 結論：
  1. 主流最佳化框架並沒有普遍採用「每次執行就自動保存完整可執行原始碼版本」；它們主要管理 run/study/optimizer 狀態、設定、結果與 checkpoint。
  2. 程式與 problem model 版本通常交由 Git；設定快照可由 Hydra，實驗追蹤與 artifacts 可由 MLflow，每次 run 的 source snapshot 可由 Sacred 這類工具承擔。
  3. 因此業界／開源生態的典型邊界是混合式：最佳化框架處理執行狀態，實驗追蹤層處理每次 run 資訊，Git／artifact store 處理長期版本與檔案。
  4. 對 OptiForge 而言，D18 需求並非只能自建；可以參考 Sacred 的每 run source capture，或整合 Git/MLflow/Hydra。但是否要保留每次快照，還是只將使用者確認的版本長期保留，仍是產品需求決策。
- 主張變化：`完整快照可能是 OptiForge 必須獨立建造的能力` → `最佳化框架本身多不管程式版本，但 Sacred、Git、MLflow 與 Hydra 已提供可整合的多種作法`。
- 適用邊界：本查核只評估框架公開文件所顯示的標準行為；使用者可自行將程式檔當作 Ray/Optuna artifact 或 checkpoint 保存，但這不等於框架已定義完整版本契約。
- 待處理問題：在「每 run 自動保存」、「只手動建版」與「自動暫存＋手動提升正式版」之間做產品選擇；再比較直接整合 Sacred 或實作精簡的 content-addressed snapshot 層。
- 外部來源：
  - [Ray Tune `Tuner.restore()`](https://docs.ray.io/en/latest/tune/api/doc/ray.tune.Tuner.restore.html)
  - [Optuna RDB study save/resume](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/001_rdb.html)
  - [Optuna Artifacts Tutorial](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/012_artifact_tutorial.html)
  - [IOHExperimenter Experiment API](https://iohprofiler.github.io/IOHexperimenter/api/ioh.Experiment.html)
  - [jMetalPy Experiments](https://jmetal.github.io/jMetalPy/tutorials/experiment.html)
  - [SMAC3 Scenario API](https://automl.github.io/SMAC3/latest/api/smac/scenario/)
  - [Hydra working directory](https://hydra.cc/docs/configure_hydra/workdir/)
  - [Sacred Collected Information](https://sacred.readthedocs.io/en/latest/collected_information.html)
  - [Sacred Observers](https://sacred.readthedocs.io/en/latest/observers.html)
  - [MLflow Tracking API](https://mlflow.org/docs/latest/ml/tracking/tracking-api/)
  - [MLflow Projects](https://mlflow.org/docs/latest/ml/projects)

### D21｜撤回算法快照需求，工作台改以保存實驗數據為主

- 討論時間：2026-09-15 17:05:03 +08:00
- 狀態：「不保存算法」已由使用者確認；實驗結果旁必須保留的最小識別資訊尚待確認。
- 與既有結論的關係：直接撤回 D18 的「完整快照可直接重跑舊版本」需求，因此 D19 對同機執行邊界的限定也不再是當前方向；不回寫舊 block，保留討論演變。D17 所說的「管理多個算法／參數／problem model 版本」也必須收縮：工作台可以管理它們在實驗結果中的身分與比較，但不保存算法實作本體。
- 討論問題：在查看既有框架如何分工後，OptiForge 是否還需要保存算法與 problem model 的完整可執行快照。
- 使用者修正：只需要保存不同實驗的數據結果，不保存算法。
- 結論：
  1. OptiForge 不建立算法原始碼、可執行程式快照或自有程式版本庫。
  2. 工作台長期保存的主體是不同實驗的數據結果，用於後續查看與比較。
  3. 工作台不再承諾只依靠自身儲存就能將任意舊算法版本直接重跑；如需保留程式歷史，應交由工作台以外的 Git 或其他版本工具。
  4. 尚未確認「只保存數據結果」是否仍包含實驗名稱、solver/problem 識別、參數、seed 與停止條件等輕量 metadata；這些資訊不等於保存算法本體。
- 主張變化：`工作台保存算法／參數／problem model 的完整可執行快照` → `工作台只長期保存實驗數據結果，不保存算法`。
- 適用邊界：本 block 討論的是工作台的長期版本儲存，不排除執行中為斷點續跑而暫時保存 solver checkpoint；後者是運行狀態，不是長期算法版本。
- 待處理問題：確認實驗結果必備的最小 metadata；重新定義工作台所謂「管理多個算法／參數／problem model 版本」是指管理比較身分，還是其中某些設定仍要保存快照。
- 依據來源：使用者在 D20 查證後的明確修正；D17–D20。

### D22｜永久保存範圍為實驗結果與當次設定

- 討論時間：2026-09-15 17:07:23 +08:00
- 狀態：結果儲存範圍已由使用者確認；不保存程式版本時如何區分同名 solver 的實作變更尚待討論。
- 與既有結論的關係：精確化 D21 的「只保存不同實驗的數據結果」；當次實驗設定仍屬結果的必要上下文，但 Git commit 與算法原始碼不納入永久儲存。這與 D06 「每場實驗保存一次原始設定」的方向相容。
- 討論問題：實驗記錄只保存數值結果，還是連同實驗設定或程式版本參照一起保存。
- 使用者選擇：保存結果加當次實驗設定；不保存算法，也不要求額外保存 Git commit 參照。
- 結論：
  1. 每場實驗的永久記錄由「數據結果＋當次實驗設定」組成。
  2. 實驗設定至少要能表達當次選用的 solver、參數、problem/model、dataset/problem instances、seed 與停止條件；精確 schema 尚待後續設計。
  3. 結果記錄不複製 solver 原始碼、problem model 原始碼、可執行快照或 container，也不強制存放 Git commit。
  4. 工作台管理的是「哪個實驗設定產生了哪些結果」，不是程式原始碼生命週期。
- 主張變化：`只保存實驗數據結果` → `保存實驗數據結果及其當次設定，但不保存算法或程式版本`。
- 適用邊界：本 block 的「實驗設定」是執行輸入與比較上下文，不等於程式環境或算法實作快照；執行中 checkpoint 仍可作為暫態恢復資料另行處理。
- 待處理問題：當 solver ID 與參數不變，但 solver 程式實作已修改時，系統如何防止不同實作被誤當成相同實驗條件。
- 依據來源：使用者本輪選擇；D06、D21。

### D23｜算法實作變更由使用者手動更新 `solver_version`

- 討論時間：2026-09-15 17:09:11 +08:00
- 狀態：算法版本識別方式已由使用者確認；忘記改版號時是否需要系統防護尚待確認。
- 與既有結論的關係：回答 D22 所留的同名 solver 實作變更辨識問題。不擴張為自動程式快照或 Git 版本整合，以設定中的顯式版號作為比較身分。
- 討論問題：當 solver ID 與參數不變、但算法程式已修改時，系統應以手動版號、自動 source hash 或只靠實驗名稱／時間區分。
- 使用者選擇：修改算法實作後，由使用者手動更改 `solver_version`。
- 結論：
  1. `solver_id` 辨識算法家族，`solver_version` 辨識該算法實作的人工宣告版本。
  2. 算法實作出現會影響行為或結果的修改時，使用者負責更新 `solver_version`；實驗設定與結果必須一起保存該值。
  3. 目前不以 source hash 作為正式版本身分，也不要求工作台自動追蹤 Git commit。
  4. 因此工作台能區分的是使用者已正確宣告的算法版本；當使用者忘記改版號時，是否要額外偵測或阻擋仍未決定。
- 主張變化：`不保存程式時尚不知如何區分實作變更` → `用使用者手動維護的 solver_version 區分，系統只保存版號與實驗資料`。
- 適用邊界：`solver_version` 是輕量 metadata，不證明兩份程式內容一定相同，也不能替代 Git 的程式歷史與還原能力。
- 待處理問題：使用者忘記更新 `solver_version` 時，系統應完全信任設定、用非持久 source hash 發出警告，或阻止版號與程式內容不一致的執行。
- 依據來源：使用者本輪選擇；D22。

### D24｜`solver_version` 完全信任使用者宣告

- 討論時間：2026-09-15 17:10:41 +08:00
- 狀態：版本宣告的責任邊界已由使用者確認。
- 與既有結論的關係：完成 D23 對漏改 `solver_version` 的邊界討論。工作台不採用 source hash 警告或阻擋，也不為此讀取算法原始碼。
- 討論問題：使用者修改算法但忘記更新 `solver_version` 時，系統應信任使用者、警告或阻止執行。
- 使用者選擇：完全信任使用者，不做自動偵測。
- 結論：
  1. 工作台將實驗設定中的 `solver_version` 當作正確且具權威的使用者輸入。
  2. 系統不計算、保存或比對 solver source hash，不根據程式內容發出版號警告，也不因版號可能過期而阻止執行。
  3. 使用者忘記更新版號時，不同算法實作可能在結果中被標成相同版本；該錯誤與比較污染風險由使用者承擔。
  4. 版本檢查不是本工作台的工程責任，因此後續架構評估不將程式反射、原始碼收集或 Git 狀態偵測視為必備功能。
- 主張變化：`以人工 solver_version 辨識算法版本，可能再加自動防護` → `solver_version 完全由使用者負責，系統不檢查程式內容`。
- 適用邊界：這項取捨降低系統複雜度，但不能對「版號與實作一定一致」提供工程保證。
- 待處理問題：進入需求實踐層，確認使用者保存多場實驗後，工作台要用哪種比較與呈現方式幫助決定下一次算法修改。
- 依據來源：使用者本輪選擇；D23。

### D25｜結果層只負責保存與匯出，不內建比較判讀

- 討論時間：2026-09-15 17:12:36 +08:00
- 狀態：結果層的產品邊界已由使用者確認；四輪需求引導已完成，等待使用者補充遺漏。
- 與既有結論的關係：精確化 D16 對「算法研發工作台」的廣義定位。工作台支援研發流程，但不代替研究者判斷算法改善，也不把分析儀表板納入核心產品。
- 討論問題：實驗完成後，工作台應只保存／匯出資料，還是應自動對齊兩場或多場實驗，產生統計、圖表、排名與趨勢。
- 使用者選擇：系統只需要保存與匯出實驗資料。
- 結論：
  1. 工作台必須可持久保存多場實驗的結果與當次設定，並以穩定、可被外部工具讀取的格式匯出。
  2. 工作台不負責判定算法是否改善，不自動產生成對實驗差異、顯著性檢定、圖表、排名、趨勢或 dashboard。
  3. 結果分析、製圖與論文報表由使用者或外部工具處理；因此匯出 schema 與穩定身分欄位比內建 UI 更重要。
  4. D16 的「工作台」應理解為算法研發實驗的執行、記錄與匯出工作區，而不是全功能研究決策平台。
- 主張變化：`算法研發工作台可管理變體並自動建立統計比較` → `工作台支援研發實驗，但結果層只保存與匯出，分析與判讀留給外部`。
- 適用邊界：不內建分析不等於不保存分析所需欄位；後續仍必須確認 raw per-run result、best solution、runtime、evaluation count、seed、solver/version、parameters、problem/model 與停止資訊的最小匯出契約。
- 待處理問題：完成遺漏補充後，整理需求摘要；再用該需求比較現有 OptiForge、直接採用外部系統與混合架構。
- 依據來源：使用者本輪選擇；D16、D22–D24。

### D26｜專業最佳化研究以假說驅動的實驗循環取代單純賽榜

- 討論時間：2026-09-15 17:22:06 +08:00
- 狀態：外部方法論查證與當前範圍評估已完成；是否將「實驗關係與研究語意」納入核心需求，待使用者確認。
- 與既有結論的關係：不否定 D21–D25 對「結果＋設定、手動 `solver_version`、保存／匯出、分析外置」的取捨；但指出這些只夠構成執行與證據儲存基礎，尚不足以解決「盲猜修改」的研發問題。
- 討論問題：專業研究者如何改進與比較最佳化算法；當前 OptiForge 只保存結果與設定並供匯出的功能範圍是否合適。
- 外部查核：
  1. Hooker 早在 1995 年就批評「提新算法→跑 benchmark→贏才發表」的 horse-race 模式：它可以告訴我們誰贏，但不能說明為什麼；受控實驗才會產生可回饋設計的理解。
  2. 算法工程文獻將研發定義為「設計／分析→實作→實驗評估→將證據送回設計」的循環；文獻同時指出，常見缺口正是實驗結果沒有回到下一次設計。
  3. 最佳化 benchmarking 綜述建議先確定研究問題，再選題庫、算法、等價 budget 與指標；分析依次分為 EDA（找模式／異常／生成假說）、confirmatory analysis（檢驗預先定義的假說）與 relevance analysis（判斷差異是否有實際意義）。
  4. 隨機算法不應由單一 seed 定勝負；需要預先確定的多個 repeat，並在同題目、同 budget 與一致初始化條件下比較。當實驗設計真正建立成對樣本時，使用同一組 seeds / common random numbers 可降低變異；但不是只要 seed 整數相同就自動構成有效成對。
  5. COCO 將到達目標值的 objective-evaluation 數視為核心度量，並要求在所有題目使用同一算法設定、初始化、budget、停止與 restart 條件。這類軌跡／target-hitting 資料能顯示「前期改善、後期停滯」，只存最後最佳值看不出機制差異。
  6. 參數改進不必靠人工盲猜：irace 以 racing 逐步淘汰差設定，SPOT 以序列模型引導下一批實驗；兩者的目標都不只是找參數，還包含理解影響。irace 並區分 train/test instances，可對 source/target configurations 進行 ablation。
  7. 文獻本身持續提醒可複製性不足、統計不當、題庫偏誤與參數過擬合，因此這些不是單一使用者才會遇到的問題，也不存在一套所有專業人員都完全遵循的固定 SOP。
- 對當前範圍的評估：
  1. 「結果＋實驗設定＋匯出」很適合當最小執行／證據層，但若把它當作完整的「算法研發工作台」，範圍過窄；它只會更有秩序地保存 horse-race 結果，不會自動讓研發收旂。
  2. 工作台不必內建圖表、顯著性檢定或自動調參，但至少要表達實驗的「研究關係」：本次相對哪個 baseline／parent、只改了哪個 factor、屬於 pilot／tuning／ablation／confirmation 哪個階段，以及使用哪組 train/test problems、seeds 與 budget。
  3. 匯出約定除了 final best／runtime／evaluation count，應能保存可選的 convergence / target-hitting 軌跡，否則外部分析工具仍無法告訴研究者「改善發生在哪裡」。
  4. 自動調參、統計與製圖可整合 irace／SPOT／SMAC／分析 notebook，不建議 OptiForge 重新實作。因此較合適的定位是「最佳化算法實驗控制與證據擷取層」，再與既有分析／調參工具混合。
  5. 現有程式已有每個 problem/repeat 的穩定 seed、每 run 最終結果、runtime、evaluation count、參數與 JSON/CSV 匯出；但尚無 `solver_version`、baseline/parent/factor/stage/split 等實驗關係、convergence trajectory，且通用 CLI 是全批結束後才寫出。
- 主張變化：`保存與匯出結果即可構成算法研發工作台` → `保存與匯出是必要基礎，但要降低盲猜，還需實驗關係、受控變因與可觀察搜尋過程的資料約定`。
- 適用邊界：這些是對「研發循環」的方法與資料需求，不代表所有統計、圖表、自動調參都必須內建進 OptiForge。
- 待處理問題：使用者是否同意將「實驗關係／階段／受控 factor／problem-seed-budget 分組／可選軌跡」納入核心 schema，而保持統計與自動調參外置。
- 外部來源：
  - [Hooker, *Testing Heuristics: We Have It All Wrong* (Carnegie Mellon University, 1995)](https://sci2s.ugr.es/keel/pdf/specific/articulo/hoo95.pdf)
  - [Barr et al., *Designing and Reporting on Computational Experiments with Heuristic Methods* (1995)](https://mauricio.resende.info/abstracts/guidelines.html)
  - [Beiranvand, Hare & Lucet, *Best Practices for Comparing Optimization Algorithms* (2017)](https://arxiv.org/abs/1709.08242)
  - [Bartz-Beielstein et al., *Benchmarking in Optimization: Best Practice and Open Issues* (2020)](https://arxiv.org/abs/2007.03488)
  - [Osaba et al., *A Tutorial on the Design, Experimentation and Application of Metaheuristic Algorithms to Real-World Optimization Problems* (2021)](https://doi.org/10.1016/j.swevo.2021.100888)
  - [Bartz-Beielstein, *SPOT: An R Package for Automatic and Interactive Tuning of Optimization Algorithms* (2010)](https://arxiv.org/abs/1006.4645)
  - [López-Ibáñez et al., *The irace Package: Iterated Racing for Automatic Algorithm Configuration* (2016)](https://doi.org/10.1016/j.orp.2016.09.002)
  - [COCO, *The Experimental Procedure*](https://numbbo.github.io/coco-doc/experimental-setup/)
  - [COCO, *Performance Assessment*](https://numbbo.github.io/coco-doc/perf-assessment/)

### D27｜確定 OptiForge 為實驗控制與證據擷取層

- 討論時間：2026-09-15 17:56:19 +08:00
- 狀態：產品定位、核心資料邊界與外部工具分工已由使用者確認。
- 與既有結論的關係：正式接受 D26 的外部查證建議，並將 D16 的「算法研發工作台」收旂為明確的系統責任；不改寫 D21–D25 已確認的儲存與分析邊界。
- 討論問題：OptiForge 是否應負責實驗關係、受控變因與搜尋過程證據，同時繼續將統計、製圖與自動調參留給外部工具。
- 使用者選擇：接受 D26 所提的定位與功能邊界。
- 結論：
  1. OptiForge 正式定位為「最佳化算法實驗控制與證據擷取層」，而非內建所有研究分析能力的單體工作台。
  2. 核心資料契約除了結果與當次設定，還必須能表達實驗關係／階段、受控改動 factor、problem-seed-budget 比較分組，並支援可選的 convergence／target-hitting 軌跡。
  3. 系統繼續保存並匯出分析所需的證據，但不內建統計判斷、製圖、dashboard 或自動調參。
  4. 統計與圖表由 notebook／R／其他分析工具處理；參數搜尋優先整合 irace、SPOT 或 SMAC，不在 OptiForge 重新實作。
  5. 系統的工程價值是將 solver/problem 注冊、可重現 task、公平實驗計畫、平行／恢復執行與穩定證據匯出組成一致邊界。
- 主張變化：`只保存結果與設定的精簡工作台` → `保存與匯出仍為主體，但核心 schema 必須同時承載實驗設計關係與可用於生成下一個假說的過程證據`。
- 適用邊界：實驗關係與軌跡是資料語意／擷取責任，不等於 OptiForge 必須自動解釋結果或決定下一個算法修改。
- 待處理問題：逐項定義 experiment identity/relationship schema、實驗階段與 problem split 語意、comparison task matrix，trajectory event 最小契約，再映射現有程式與排定改造順序。
- 依據來源：使用者對 D26 建議的明確接受；D21–D26。

### D28｜每個算法版本獨立 experiment，比較關係與執行發布分離

- 討論時間：2026-09-19 02:04:02 +08:00（結論確認後記錄；前三輪攻防的個別時間未另行擷取）
- 狀態：方案 B 已由使用者確認；參數組粒度與比較關係 schema 尚待討論。
- 與既有結論的關係：依使用者指示移除原 D28–D30，重新討論 experiment 邊界；保留 D01–D27。沿用 D06–D11 的同名成功替換、失敗保護與續跑需求，以及 D21–D27 的保存與分析分工，不以本 block 恢復已移除的名稱／variant identity 決策。
- 討論問題：一場 experiment 應包含多算法設定的完整比較計畫（A），還是每個算法版本各自執行，事後明確組織比較（B）。
- 使用者需求：頻繁修改算法、參數與 problem model；每個算法跑完即可交 AI 分析及比對，不要求多算法共同完成才發布。
- 決策過程：各角色由獨立 agent 擔任，僅交換公開發言；依序完成質詢、系統工程異端、實驗設計異端三組攻防。
  1. 質詢修士假設兩場獨立實驗使用相同 problem／seed／budget 並完整保存結果與設定。捍衛騎士承認 A 不具必然獨占的公平性保障，不能以「公平比較必須 A」證成原提案。
  2. 系統工程異端提出甲新版成功、乙失敗的情境。按 A 與整場成功才替換的既定語意，甲可先分析已保存的新進度，但正式更新仍須等乙；捍衛騎士承認耦合代價，退守到「使用者希望完整比較整體發布時才支持 A」，此條件尚未被使用者接受。
  3. 實驗設計異端區分確認比較與分析後新增的探索算法：共用矩陣不使後續探索自動成為原確認比較的成員。捍衛騎士承認完整比較清單不推出共同正式更新門檻，放棄目前推薦 A 的理由；仲裁不將此推廣為 A 在所有情境均無用。
- 使用者選擇：接受仲裁提出的方案 B 候選邊界，授權立即寫回並繼續下一題。
- 結論：
  1. 每個算法版本及其明確設定範圍各自構成一場 experiment，独立執行、續跑與完成；成功後替換自己的同名舊正式結果與設定，失敗則保留上一版完整正式結果及可續跑的新進度。
  2. 不同 experiment 可共用明確的比較條件，並記錄比較關係、研究階段與受控改動；不要求它們住在同一 experiment 或共同完成才發布。
  3. 系統保存結果與實際設定並匯出證據；統計、圖表與 AI 分析仍外置。採 B 本身不保證任意兩場實驗都可公平比較，具體條件與成員必須另行明確定義。
  4. 同名成功覆寫且未另存的舊結果不再存在時，不能僅凭關係紀錄聲稱原比較仍可重現；本 block 不新增強制歷史保存需求。
- 主張變化：`完整多算法比較應放同一 experiment` → `公平性不必依靠共同容器` → `A 僅適用於整體發布偏好` → `完整比較清單不推出共同發布，放棄本輪 A 推薦` → `接受算法版本独立 experiment 的 B`。
- 適用邊界：本 block 定義算法版本間的執行與發布邊界；不決定每組參數是否各自拆場、是否保留 variant 層、experiment identity、比較成員引用方式或發布儲存機制。被移除的原 D29–D30 不作為已確認前提。
- 待處理問題：先定義同一算法版本多組參數的 experiment 粒度，再討論 experiment identity 與跨實驗比較關係、階段及共享條件。
- 依據來源：使用者本輪明確接受；D06–D11、D21–D27；三輪公開攻防的條件推論。本輪未新增外部查證。

### D29｜同算法版本的多組參數整批成功後更新正式結果

- 討論時間：2026-09-19 02:20:06 +08:00（使用者選擇後記錄；三輪攻防未逐輪擷取時間）
- 狀態：同批正式更新邊界已由使用者明確選擇；組層身分與現行 RNG 流程尚待檢查。
- 與既有結論的關係：補足 D28 未決的參數集合粒度，不恢復跨算法的共同 experiment 提案；沿用 D06–D11 的同名成功替換、失敗保護與續跑需求。追加本 block，不改寫前文或恢復已移除的舊 D29–D30。
- 討論問題：同一算法版本的多組參數是否必須各自一場 experiment，還是可共同構成一場並整批更新。
- 初始主張：每組參數獨立一場 experiment，但允許批量啟動；使用者同意以此主張辯論，並未預先接受該方案。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 質詢修士指出同名 E 修改參數後成功覆寫的既有需求，與「每份參數必須取得不同 experiment 身分」不一致；騎士收縮為每次執行只含一組參數，同名後續仍可改設定，區分執行範圍與跨次身分。
  2. 系統工程異端指出完整參數掃描也可是一份成果，多組共同完成後發布不違反既有規則；騎士撤回單組強制限制，僅建議逐組作為預設，並承認多組也可保存場內續跑進度。
  3. 實驗設計異端指出「頻繁改參數」及「每算法跑完先分析」不等於「每組參數完成即分析或正式更新」；騎士承認推論缺乏依據，放棄逐組預設推薦。仲裁轉向澄清實際成果更新需求，未判定集合模式普遍更好。
  4. 使用者明確選擇整批一起更新，提出起始 seed 固定、部分新舊結果混合可能造成 seed 不同步的擔憂。騎士採納共同發布需求，但不將 seed 不同步視為已驗證的必然結果；仲裁確認成果更新邊界已解決。
- 結論：
  1. 同一算法版本的一場 experiment 可包含預先設定的多組參數；不強制每組參數拆成不同 experiment，也不以逐組拆場作為本輪推薦預設。
  2. 該場所有參數組及其預定 tasks 全部成功、完整產出後，才一起替換同名上一版正式結果與對應設定；不部分更新其中一組的正式結果。
  3. 若其中一組失敗或尚未完成，上一版完整正式結果與設定保持不變；本次已完成工作與完整 checkpoint 仍持久化保存供續跑，不因整批發布而回退為整批重算。
  4. 不同算法版本仍按 D28 分場；批量啟動多場 experiment 不因此要求不同場次共同成功才發布。
  5. AI 分析時機與正式發布邊界可分開；本輪不新增「必須全部完成才允許分析進度」的限制。
- 主張變化：`每組參數必須独立` → `單次一組，但同名重跑可改參數` → `逐組僅作預設` → `缺乏需求依據，撤回預設推薦` → `使用者選擇同版本多組參數整批正式更新`。前三輪候選已由最後需求選擇取代。
- 理由與待驗證事項：使用者的 seed 同步擔憂原樣保留為需求動機，不寫成現行程式事實。若 root seed 與派生映射均相同，部分完成本身不必導致 seed 改變；具體配置、seed 派生或 RNG 消耗是否會使現行流程不同，尚未查證。正式結果須屬於同一次完整產出的集合，是本題已確定的發布需求，不是對 RNG 演算法的驗證。
- 適用邊界：不決定參數組名稱、身分生成、task key、配置改動後 checkpoint 是否相容、儲存載體或安全發布的具體實作；不新增強制歷史保存或同時支援多種發布模式的要求。
- 待處理問題：定義場內參數組的標識，使設定、結果與續跑進度可正確對應；另行檢查現行 seed 派生與 RNG 消耗流程。
- 依據來源：使用者本輪明確選擇；D06–D11、D21–D28；三輪公開攻防與需求重整的條件推論。本輪未新增外部查證或修改程式。

### D30｜參數組採單一場內組代號，同次執行與續跑期間固定

- 討論時間：2026-09-19 02:29:31 +08:00（使用者確認後記錄；三輪攻防未逐輪擷取時間）
- 狀態：最小識別契約已由使用者接受；代號產生與設定變更後的進度對應規則尚未決定。
- 與既有結論的關係：補足 D29 的場內參數組識別需求，保留 D28 的算法版本分場與 D29 的整場成功更新；不恢復已移除的舊 D30 variant_name 決策，不改寫前文。
- 討論問題：參數組應以人工名稱、系統產生的識別，或識別與顯示名稱兩層對應結果與續跑進度。
- 初始主張：每組參數必須人工指定場內唯一名稱，結果與進度引用該名稱，實際參數仍完整保存。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 質詢修士以數百組參數組合、無逐組取名意圖的假設反例，挑戰人工命名的必要性。騎士承認人工名稱沒有不可替代的恢復保障，撤回強制人工取名，改提識別可由系統提供、人工命名為便利選項；此反例不構成已確認的自動 grid 功能需求。
  2. 系統工程異端指出可改名稱直接作引用識別，純改名可能要求同步更動結果與進度引用。騎士採納識別與顯示名稱分離作為修正候選，但未確認使用者需要改名，也未指定 UUID 或實作機制。
  3. 實驗設計異端指出未確認「改顯示名稱而保留原引用」的研究操作，單一執行期間固定的可讀組代號也能作為較簡單候選。騎士放棄雙層識別推薦；仲裁提出最小契約，使用者明確接受。
- 結論：
  1. 每組參數有一個場內唯一、可讀的組代號（group key）；結果與本次續跑進度用它對應。
  2. 同一次執行及其中斷接續期間，組代號保持不變。
  3. 完整保存各組實際參數；不以代號代替設定或判定參數內容。
  4. 不要求額外 UUID 或獨立顯示名稱欄位，也不強制逐組人工取名；人工指定或系統產生的具體方案另行決定。
  5. 組代號不在本題綁定 seed，代號相同也不構成沿用 checkpoint 的充分條件。
- 主張變化：`強制人工唯一名稱` → `名稱可由系統提供，人工命名或改名為便利選項` → `引用識別與顯示名稱分離` → `缺乏改名需求依據，撤回雙層推薦` → `接受同次執行期間固定的單一組代號`。前面候選保留為演化，不作為最終需求。
- 適用邊界：本 block 不決定代號產生算法、是否允許人工覆寫、重排或插入參數組後的對應方式、跨次執行的永久身分、設定變更後 checkpoint 相容性或錯誤處理。group_001 僅為示例，不代表已決定使用列表位置或自動編號；固定代號本身不保證自動產生的代號對重排穩定。
- 待處理問題：定義組代號由人工指定或系統產生的規則，再處理參數組重排、增刪與配置修改對續跑的影響。
- 依據來源：使用者本輪明確接受；D06–D11、D21–D29；三輪公開攻防的條件推論。LLM 背景知識開啟但未作外部查證；本輪未新增來源、檢查現行程式或修改程式。

### D31｜組代號可人工指定或自動生成，保存對應作為執行與匯出依據

- 討論時間：2026-09-19 02:40:31 +08:00（結論確認後記錄；三輪攻防未逐輪擷取時間）
- 狀態：整體方案已由使用者接受；生成算法、匯出格式與設定修改後 checkpoint 相容政策未定。
- 討論問題：如何兼容人工與自動組代號，並讓保存設定、實際執行及結果辨認保持一致。
- 初始主張：啟動前可指定 key，未填則自動生成；保存最終 key／完整參數對應，續跑沿用保存對應，不按目前列表重新編號。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 質詢修士提出人工 key 與自動生成候選撞名。騎士補充先保留人工 key，人工重複拒絕啟動，自動生成避開已用代號，最後驗證唯一再保存；具體生成算法未定。
  2. 系統工程異端提出不同 tasks 共用可變參數物件，導致保存兩份正確設定、實際卻跑同一份的條件反例。騎士接受缺口，補充 tasks 從保存對應取得並固定自己的參數，不受其他組改寫；保存本身不足以保證存跑一致。
  3. 實驗設計異端指出大量自動代號不直接表達參數，可能增加辨認成本。騎士接受，收縮 key 的效益為引用與恢復識別，補充結果須能連同完整實際參數讀取或匯出；不增加顯示名稱層或內建分析。
- 結論：
  1. 組代號可人工填寫，未填則系統產生；人工重複拒絕啟動，自動生成避開人工及已生成代號。
  2. 驗證場內唯一並保存最終 key／完整實際參數對應後才開始 tasks；每個 task 使用該對應並綁定不被其他組後續修改的參數值，不在執行時另讀可變設定。
  3. 同次執行的恢復沿用保存對應，不依目前列表重新編號；恢復建立 tasks 亦遵守固定參數規則。
  4. 提供結果時，可連同各 key 對應的完整實際參數讀取或匯出，不只提供代號與成績；比較、統計及排名仍外置。
- 主張變化：`可人工或自動命名並保存對應` → `補上混用避碰校驗` → `接受保存不等於執行一致，補上 task 固定參數` → `接受代號不等於容易理解，結果與參數一併提供`。兩位異端的反例被採納，不記為已被駁倒。
- 適用邊界：沿用 D28–D30；不要求 UUID、獨立顯示名稱、複製所有共享資源或代號綁定 seed。未決定自動生成算法、具體輸出 schema、保存的 crash 安全或修改設定後是否可沿用 checkpoint；同 key 不證明相容。本輪未檢查程式，不能宣稱已實作或驗證。
- 待處理問題：設定重排、增刪或修改後，如何區分接續原執行與啟動新執行，以及哪些進度可沿用。
- 依據來源：使用者本輪明確接受；D06–D11、D21–D30 公開前提；三輪條件推論及共享可變狀態的一般背景知識。未新增外部查證。

### D32｜任何執行設定修改都開新執行，續跑沿用原保存設定

- 討論時間：2026-09-19 02:50:54 +08:00（使用者確認後記錄；各輪時間未另行擷取）
- 狀態：保守產品政策已由使用者確認；設定內容的比較方式與跨執行重用尚未決定。
- 討論問題：中斷後修改設定，應接續原執行還是開新執行，如何判斷修改是否安全。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 初始主張是續跑沿原保存設定，任何修改則開新執行。質詢修士以 worker 八降二、其他求解條件不變的假設邊界挑戰；騎士收縮為只有影響實驗條件或 checkpoint 接續語義才開新執行，未確認現行 worker／RNG 行為。
  2. 系統工程異端指出名為效能選項的 evaluation_batch_size 仍可能改變 solver 搜尋路徑。騎士採納，提出僅允許事先列入續跑可調清單的變更，其他差異或影響未知時開新執行；清單責任未定。
  3. 實驗設計異端假設中途加密軌跡已確認不改求解與停止條件，指出未列入清單不等於研究上必須另開執行。騎士採納，放寬為清單外有明確安全依據也可續跑；但誰確認、何種依據足夠仍未解決。
  4. 使用者選擇避免誤判風險，主張任何設定修改都開新執行。騎士採納此新產品偏好，撤回可調清單及清單外例外；仲裁呈現新版規則後，使用者明確確認。
- 結論：續跑只沿用該次執行保存的設定；任何執行設定修改都開新的執行嘗試，不直接改寫原執行設定或混入其進度。即使只是調整 worker 數，也不提供本題的安全例外。
- 主張變化：`任何修改開新執行` → `依求解／接續影響判斷` → `僅清單內可改` → `清單外確認安全也可` → `使用者風險優先，恢復統一保守政策`。中間方案已由最後選擇取代；反例保留為有效挑戰，不記為被駁倒。
- 理由與代價：不要求系統或使用者判斷每項改動是否影響結果，接受可能不必要地另開執行的代價；這不是宣稱所有設定修改必然改變結果，也不保證原始碼或 checkpoint 相容。
- 適用邊界：沿用同名成功整場替換、失敗保留舊正式結果，以及未改設定時的長 task 斷點恢復需求；不新增算法快照或推翻人工 solver_version 信任。何謂執行設定、註解／排版與實際值如何比較尚未定，不承諾逐 byte 比對；新執行能否重用舊完成 tasks／checkpoint 另議，不能由本結論推出必須從頭重算或必可重用。
- 待處理問題：先明確定義設定差異的比較範圍，再決定新執行與舊進度的重用邊界。
- 依據來源：使用者本輪風險偏好與明確確認；D06–D11、D21–D31 公開摘要；各輪條件推論。LLM 背景知識開啟，未新增外部查證、檢查程式或修改程式。

### D33｜以完整最終執行設定判定差異，保留型別與列表順序

- 討論時間：2026-09-19 02:59:50 +08:00（整體方案確認後記錄；各輪時間未另行擷取）
- 狀態：設定比較與缺項處理已由使用者確認；實作尚未驗證。
- 討論問題：D32 的「設定修改」應比較文件文字還是實際執行值，如何處理預設、覆寫、列表與型別。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 初始候選比較解析後實際設定，註解與排版不算修改。質詢修士以省略 max_iter、實際預設 100，與明寫 100 的假設指出純文件解析不足；騎士補上由實際執行機制取得適用預設後比較，不猜測省略等於明寫。
  2. 系統工程異端提出比較時取預設 100、啟動時另被本機設定覆寫為 200。騎士採納，補上所有來源與覆寫完成後的同一份最終設定，供比較、保存與建立 tasks 使用，判定後不得另行覆寫。
  3. 實驗設計異端提出步長列表重排可改變搜尋順序；騎士採納，補上列表預設按原順序逐項比較，不排序抹平差異，未新增無序集合機制。
  4. 質詢修士假設整數 1 表示選一個候選、浮點數 1.0 表示選全部。騎士補上同時比較最終型別與值，只承認實際啟動解析本來的轉換，不為通過比較額外強轉。
  5. 仲裁指出最終設定未知不能靠另開執行解決，提出停止報錯、不猜續跑或直接新開；使用者先接受此項，再確認整體方案。
- 結論：
  1. 比較真正執行採用的完整最終設定，不比較 YAML 文件字節；只改註解或排版不算設定修改。
  2. 由實際設定處理／solver 機制取得適用預設值，處理所有適用來源與覆寫；同一份最終設定用於比較、保存及建立 tasks，判定後不得再由其他來源覆寫執行值。
  3. 列表預設保留原順序逐項比較；型別與值同時比較。只有實際執行解析本來就轉成同型同值時，才按轉換後設定判同，不另做比較專用強轉。
  4. 無法取得完整最終設定時，停止並報錯指出缺項；不猜測可續跑，也不直接開始新執行。
  5. 按上述方式判定實際設定不同時，依 D32 開新執行，不重新引入 worker 或其他安全例外。
- 主張變化：`比較解析後設定，忽略文件表面差異` → `補齊真正適用預設` → `比較與啟動共用覆寫後最終設定` → `保留列表順序` → `保留最終型別與值` → `不完整則停止報錯`。有效反例被採納或由新增規則回答，不記為對手被駁倒。
- 適用邊界：不宣稱最終設定相同就自動捕捉任意 solver 隱藏取值、外部資料或原始碼變更；人工 solver_version 信任與不保存原始碼快照不變。未決定完整 schema、序列化格式、欄位集合或跨新舊執行重用 tasks／checkpoint 的規則；本題不要求新增無序 schema 或安全分類機制。
- 待處理問題：設定修改後的新執行，是否及如何重用舊已完成工作或 checkpoint；之後將設定契約映射現有程式並驗證。
- 依據來源：使用者本輪明確確認；D06–D11、D21–D32 公開摘要；各輪條件推論與一般背景知識。未新增外部來源、檢查或修改程式；保留前文不改寫。

### D34｜跨執行重用先滿足公平與正確，再討論效率

- 討論時間：2026-09-19 03:10:08 +08:00（使用者明確指出優先序後記錄；各輪時間未另行擷取）
- 狀態：優先序已由使用者明確指定；完成結果重用與 checkpoint 重用政策仍未定案。
- 討論問題：改設定開新執行後，是否可重用舊工作，以及公平、正確與效率的判斷順序。
- 決策過程：各角色由獨立 agent 擔任，只交換公開发言。
  1. 初始候選新執行預設全部重跑、不自動重用舊結果或 checkpoint。質詢修士以 99 組未變且已完成、只改最後失敗組的成本反例挑戰；騎士撤回長期全面重跑推薦，退守為重用規則未確認前暫不自動繼承，完成結果與半途狀態分開討論。
  2. 系統工程異端假設插入 task 改變實際 seed 分配，指出參數組不變不等於相同評估。騎士採納，提出核對 solver／人工版本、實際參數、problem 實際輸入、task 實際 seed／初始 RNG、停止條件及 budget；此清單僅為必要條件候選，不是已批准的充分重用規則。
  3. 實驗設計異端假設相同時間上限下舊結果來自繁忙環境、新組來自空閒環境，指出輸入相同不等於相同測量意義。騎士採納，但仲裁隨後先問使用者是否希望沿用未變結果，漏掉公平與正確的前置判斷。
  4. 使用者明確糾正：必須先保證實驗公平與正確，才能討論效率優化。騎士與仲裁承認前一問法不當，將新版主張改為先確認重用符合比較目的且公平、正確依據充分，再評估節省成本；依據不足不自動重用。
- 確認結論：公平與正確是不可用效率交換的前提，不詢問使用者以省時接受失公平的結果；只有满足前提的方案才進行效率比較。此處確認的是決策原則，不是已完成公平性驗證或准許某種重用。
- 主張變化：`長期預設全重跑` → `規則未定前暫不自動繼承` → `提出實際 task 核對但不足以批准` → `測量用途亦須相符` → `使用者糾正優先序，公平正確先於效率`。
- 適用邊界：D32–D33 的設定變更開新執行與最終設定比較規則不變；原執行沿保存設定的長 task 恢復仍支持。不批准全部沿用或永久全部重算，不宣稱固定迭代／輸入匹配就自動保證時間、資料或所有比較公平；跨執行 checkpoint 相容仍另議。
- 待處理問題：先界定比較解品質與比較時間表現時，哪些舊完成結果可提供正確、公平的比較證據，再決定是否重用及其最小規則。
- 依據來源：使用者明確優先序；D06–D11、D21–D33 公開摘要及本題公開條件推論。未新增外部查證、檢查或修改程式；保留先前討論不改寫。

### D35｜只支援原執行完整續跑，新執行全部重跑、不自動重用舊工作

- 討論時間：2026-09-19 03:13:24 +08:00（使用者確認後記錄）
- 狀態：本階段產品範圍已由使用者確認；斷點保存與恢復的具體實作仍待設計、驗證。
- 討論問題：是否加入跨執行結果／checkpoint 重用，或先專注同一執行的中斷恢復。
- 決策過程：沿用 D34 的獨立角色與公開攻防。
  1. 實驗設計異端指出品質與耗時的證據適用範圍不同：在固定工作量、輸入核對與解驗證成立的假設下，舊品質可供比較，舊秒數卻不能自然代表新測量。騎士接受，但區分「可作既有觀測」與「自動納入新正式成果」，不將前者當成重用許可。
  2. 仲裁推薦簡化候選：先只支援原執行完整續跑，不做跨執行自動重用。使用者表示看不懂；具體說明為設定未改則跳過已完成 task、未完成長 task 從 checkpoint 接續，設定改了則新執行全部重新跑，即使部分 task 未受影響亦同。
  3. 使用者在此說明後明確接受，未再啟動原建議的工程攻防；不記錄未發生的辯論。
- 結論：
  1. 設定未改、原執行因中斷而接續：保留並沿用已完成工作；未完成 task 從已成功持久化的 checkpoint 接續，不要求從頭重跑。
  2. 按 D33 判定執行設定修改、依 D32 開新執行：全部重新跑，不自動沿用舊執行的已完成結果或 checkpoint；接受未變 task 也重算的成本。
  3. 本階段不建置跨執行自動重用及其相容性／指標適用判定機制。舊結果仍可作外部分析參考，不冒充新執行產出或新增 repeat。
- 主張變化：`D34 中未確認重用規則、僅暫不繼承` → `區分證據可比較與正式重用` → `用具體中斷／改設定情境釐清` → `使用者接受本階段原執行續跑、新執行全重跑的簡化範圍`。不改寫 D34 曾撤回長期全面重跑推薦的脈絡，也不宣稱先前反例被駁倒。
- 適用邊界：公平與正確仍先於效率；不聲稱全重跑本身就保證所有比較公平。沿用同名新執行成功後整場替換、失敗保留上一版完整正式結果；本結論不授權清除舊進度或保存算法快照，不保證恢復未寫入 checkpoint 的最後一段工作或尚未驗證的 solver 狀態。
- 待處理問題：定義同一原執行恢復所需的 solver／RNG／進度狀態、保存時點、時間預算接續規則，以及不具備內部恢復能力的 solver 如何處理。
- 依據來源：使用者對具體簡化方案的明確接受；D06–D11、D21–D34 與本輪公開條件推論。未新增外部查證、檢查或修改程式；保留前文。

### D36｜同一安全點保存全部接續必要狀態，以路徑對照驗證恢復

- 討論時間：2026-09-19 03:20:01 +08:00（使用者確認後記錄；各輪時間未另行擷取）
- 狀態：保存範圍、安全點與驗證原則已由使用者確認；具體實作尚未驗證。
- 討論問題：未完成長 task 要正確接續，checkpoint 應保存什麼，如何取得恢復正確的證據。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 初始候選保存 solver 內部狀態、所有相關 RNG 當前狀態、進度／已耗預算及執行／task 歸屬，不只保存初始 seed。質詢修士以平行評估與 RNG 持續更新的假設指出欄位齊全仍可能來自不同時刻；騎士補上 solver 定義一致安全點，停止派新工作，讓當前步驟的在途評估完成並收納結果，凍結更新後同點截取。
  2. 系統工程異端假設外部目標評估器使用累積 mean，指出只保存 solver 內部會漏掉接續必要狀態。騎士接受，擴大範圍至所有必要的有狀態依賴；可重建部分不能額外推進 RNG 或改變接續位置。此評估器是算法的目標評估依賴，不是篩選／收集 seed 的優化器。
  3. 實驗設計異端指出恢復多耗一次 RNG，可能改變候選序列卻仍得到同一最佳分數。騎士接受，補上固定工作量下的短段路徑與狀態對照；仲裁建議整體候選，使用者明確接受。
- 結論：
  1. 每個 solver 定義一致的安全保存點；同點保存全部接續必要的算法／依賴狀態、所有相關 RNG 當前狀態、進度與已耗預算，以及執行嘗試／task 歸屬。靜態設定可引用該執行已保存設定，不要求整個程序記憶體快照。
  2. 有狀態必要依賴須保存恢復，或能在不改變隨機位置及接續進度的前提下重建；缺少必要狀態不能宣稱 checkpoint 可正確接續，不因此禁止所有 solver 註冊。
  3. 在同裝置、相同設定與初始隨機狀態、固定工作量的少量開發測試中，對照不中斷與保存後恢復：從同一安全點往後比較短段候選序列、評估值、進度、已耗工作量預算，以及段末 RNG／必要依賴狀態。不只檢查最終分數。
  4. 測試提供特定案例的證據，不把有限案例當作全部 solver 情況的通用保證；不要求每次正式實驗永久保存大量搜尋軌跡。時間停止模式不承諾精確重播，亦不要求跨裝置結果一致。
- 主張變化：`列出 solver／RNG／進度欄位` → `補上同點一致截取` → `必要狀態不以模組邊界切割` → `最終分數不足，補上路徑與狀態對照證據`。有效反例被採納，不記為被駁倒；未指稱現行程式已有上述缺陷。
- 適用邊界：沿用 D35 原執行續跑、新執行全部重跑；安全截取不等於已成功持久化，也不保證未保存區段零損失。未決定各 solver 的具體狀態清單、比較方式、時間預算接續、保存頻率／載體或不支援內部恢复的處置；未新增算法快照或每次實驗大量環境紀錄。
- 待處理問題：下一題討論中斷後時間上限如何接續計算；保存頻率與不支援恢復的 solver 另分題討論。
- 依據來源：使用者本輪明確接受；D06–D11、D21–D35 公開前提與三輪條件推論。LLM 背景知識開啟，未新增外部查證、檢查或修改程式；保留前文。

### D37｜時間額度跟隨 checkpoint 進度，未保存耗時一起回滾

- 討論時間：2026-09-19 03:26:54 +08:00（使用者明確選擇後記錄；各輪時間未另行擷取）
- 狀態：未保存工作耗時的恢復規則已由使用者選定；完整計時邊界尚未定案。
- 討論問題：時間受限 task 恢復時，checkpoint 後已執行但未保存的工作耗時是否扣除剩餘額度。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 初始候選累計求解／評估牆鐘時間，停機、暫停保存及恢復載入不扣額度。質詢修士提出上限 600 秒、checkpoint 已耗 240 秒、之後執行 300 秒未保存便停機，詢問恢復剩 360 秒或 60 秒。
  2. 騎士改為全部實際投入都扣，丟失工作也算；但承認 checkpoint 無法提供未保存區段的耗時。系統工程異端以相同 checkpoint／重啟時間、不同求解與停機時長的反例指出不可區分；騎士接受，退守為無可靠耗時依據時暫停時間受限 task 自動續跑。
  3. 仲裁指出上述計費政策並非使用者既定需求，且暫停續跑與長 task 恢復目標衝突，先詢問時間上限的意義。使用者表示看不懂，改以 60 分鐘上限、20 分鐘保存、之後 10 分鐘未保存中斷說明，使用者明確選擇恢復後仍可跑 40 分鐘。
  4. 騎士採納，撤回丟失工作必須扣及因此餘額未知便暫停續跑的候選；仲裁確認這是預算意義的需求選擇，不記為工程反例被駁倒。
- 結論：原執行續跑時，時間額度依成功保存的 checkpoint 累計耗時恢復，與算法進度一起回滾；未保存的工作進度與耗時都不沿用。例上限 60 分鐘、checkpoint 記 20 分鐘，恢復後仍有 40 分鐘，不論中斷前另做但丟失的 10 分鐘。停機期間不扣求解額度，恢復不重新給滿額時間。
- 主張變化：`依 checkpoint 恢復餘額的候選` → `反例後要求丟失工作也扣` → `證據不足，退守暫停自動續跑` → `釐清使用者需求，改為進度與時間一起回滾`。不再把全部實耗計費當作公平的必要條件。
- 適用邊界：此上限限制可恢復求解路徑的累計時間，不保證含丟失／重算工作在內的總實耗不超過上限；時間停止仍不承諾精確重播。沿用固定迭代與時間任一先到即停止、D35 原執行續跑及 D36 同點保存；未確認保存／載入開銷是否計入、起始初始化計時或其他完整計時細節，也未完成公平性或實作驗證。
- 待處理問題：由系統工程異端檢驗 checkpoint 保存／恢復開銷的計時邊界；保存頻率與不支援恢復的 solver 另議。
- 依據來源：使用者明確選擇「還能跑 40 分鐘」；D35–D36、公開攻防與本輪需求重整。LLM 一般背景知識開啟，未新增外部查證、檢查或修改程式；保留前文。

### D38｜保存與載入狀態不扣求解額度，實際求解／評估仍計時

- 討論時間：2026-09-19 03:30:05 +08:00（使用者確認後記錄；各輪時間未另行擷取）
- 狀態：恢復開銷分類與比較結論邊界已由使用者確認；完整計時實作未驗證。
- 討論問題：checkpoint 保存／恢復開銷是否扣時間額度，以及這份額度能支持什麼算法比較。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 原候選將暫停保存與恢復載入排除。系統工程異端假設恢復程序花 5 分鐘重新評估候選、重建快取，指出不能只因流程叫恢復就免計。騎士採納，改為按實際工作內容分類：必要狀態保存／載入／裝配排除，實際求解或 problem 評估仍計入。
  2. 實驗設計異端假設兩算法都完成 60 分鐘扣帳求解，保存／載入卻分別耗 30 分鐘與數秒，指出相同求解額度下品質較好，不代表相同總投入下更有效率。騎士採納比較限制；仲裁呈現整體候選，使用者明確接受。
- 結論：
  1. 必要狀態的保存、載入與裝配不扣求解時間額度；實際執行算法或 problem 評估要扣，即使包在恢復程序內、用於重建快取且未增加迭代次數亦同。不按流程名稱一律免計。
  2. D37 不變：上限 60 分鐘、checkpoint 已耗 20 分鐘，恢復起點仍有 40 分鐘；若恢復另執行 5 分鐘評估，消耗此額度後剩 35 分鐘，原先丟失的工作時間仍不扣。
  3. 說明文件交代這是求解時間額度，不是從開始到完成的總時間。相同扣帳額度可支持該額度下的品質比較，不能直接推出相同總投入下更有效率；整體效率主張另需相應總時間證據，不因本題強制新增結果標籤、資料欄位或每次執行的全面採集。
- 主張變化：`整段保存／恢復排除` → `按實際工作內容分類，恢復評估也扣` → `補上求解額度與整體效率的比較邊界`。兩個有效反例被採納，不記為被駁倒。
- 適用邊界：同額度不是比較公平的充分證明，設備、負載及其他條件仍可能影響判斷；不宣稱上述分類是所有研究目的的通用公平規則。沿用 D35–D37；尚未定初始化何時開始計時、額度用盡但恢復未完成如何處理，以及具體分類與計時實作，不能宣稱完整時間契約已完成。
- 待處理問題：先討論初始化的計時起點與範圍，再處理恢復期間額度用盡的停止行為；保存頻率、不支援恢復的 solver 仍另議。
- 依據來源：使用者本輪明確接受；D35–D37 公開前提與工程／實驗設計公開條件推論。LLM 一般背景知識開啟，未新增外部查證、檢查或修改程式；保留前文。

### D39｜算法初始化計時，前置準備與起始資源須區分

- 討論時間：2026-09-19 03:35:49 +08:00（使用者確認後記錄；各輪時間未另行擷取）
- 狀態：初始化計時範圍與起點資訊保存原則已確認；具體分類與實作未驗證。
- 討論問題：算法初始化從哪一步開始扣時間，如何避免共用準備或外部初解造成未辨認的比較差異。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 初始候選從算法相關計算開始計時，包含算法專用預處理、初解／種群生成與首次評估，不等第一輪迭代。質詢修士以距離矩陣首次建立扣 10 秒、後續 task 使用快取免費的反例挑戰；騎士採納，提出固定 problem 共用準備應於各 task 計時前一致提供，不讓啟動順序直接決定扣費。
  2. 系統工程異端以預先計算全部可行解分數的共用表指出：只依賴 problem 仍可能已代做評估。騎士採納，修正為按工作內容區分；原始輸入讀取／問題表示可前置，實驗額外求解或候選評估不能因共用而免費，原輸入已有數值不追溯製作成本。
  3. 實驗設計異端以一算法取得外部優質初解、另一算法從零生成種群指出計時正確不保證純算法歸因。騎士採納，補上實際設定表達初始化方式與外部起點來源；仲裁呈現整體範圍，使用者明確接受。
- 結論：
  1. task 從算法相關計算開始扣求解時間額度，包含算法專用預處理、初解／種群生成及首次評估。例 60 分鐘上限，上述初始化已耗 5 分鐘，進入第一輪時剩 55 分鐘。
  2. 原始輸入讀取、建立問題表示與一般框架啟動可前置；共用準備須在各 task 前一致提供，但實驗額外求解／評估不能因只依 problem、可共用或命名為準備就移出額度。原始輸入已有資料不追溯其製作成本。
  3. 保存的實際設定表達初始化方式：算法生成，或外部提供初解／種群；外部起點保存內容或可辨識引用，連同結果供外部分析。不強制不同算法使用同一初解，不新增大量快照或結果標籤。
  4. 說明與分析須區分起始資源差異：不同起點的比較結論包含這項差異；依據不足不能把暖啟動收益全部歸為算法優勢。
- 主張變化：`算法初始化即計時` → `補上一致共用準備，避免首算者獨自扣費` → `只看依賴不足，避免預計算評估免費` → `補上起始資源資訊與歸因邊界`。有效反例被採納，不記為被駁倒或現行缺陷。
- 適用邊界：模糊的問題／算法準備分類須明確確認，共享評估如何計費另議，不默認批准共享免計，也不全面准許或禁止距離矩陣。系統不保證自動辨識任意程式的隱藏工作或未聲明外部資料；引用不保證未來資料不變，共用準備不保證快取熱度及所有效能條件一致。沿用 D35–D38，未新增全面快照、逐次 hash 或公平性通用保證。
- 待處理問題：恢復途中時間額度耗盡如何停止及產出結果；保存頻率、不支援恢復的 solver 仍另議。
- 依據來源：使用者本輪明確接受；D35–D38 公開前提與三輪公開條件推論。LLM 一般背景知識開啟，未新增外部查證、檢查或修改程式；保留前文。

### D40｜求解時間額度是截止約束，不等當前步完成而延長

- 討論時間：2026-09-19 03:59:18 +08:00（使用者明確選擇後記錄；各輪時間未另行擷取）
- 狀態：截止語義已確認；可靠停止機制與結果處置未定。
- 討論問題：恢復途中額度耗盡時，能否等不可中斷的工作完成再停。
- 決策過程：各角色由獨立 agent 擔任，只交換公開發言。
  1. 使用者同意以「不開始新工作、在安全位置停止；只輸出已有完整已驗證解」作候選開始辯論，不是確認最終處置。
  2. 質詢修士假設恢復剩 2 分鐘卻需一次不可中斷的 30 分鐘評估，指出安全點停止仍超額 28 分鐘。騎士採納，提出須有可靠停止能力或保證在餘額內完成才開始，但仲裁指出尚未知使用者是否要求嚴格截止。
  3. 使用者表示看不懂，改以第 58 分鐘開始 30 分鐘計算、可能延至第 88 分鐘說明；使用者明確選擇「不允許它超過第 60 分鐘」。騎士採納截止要求，撤回等當前步完成而任意超時的候選，仲裁確認只定案需求、不連帶批准機制。
- 結論：累計求解計費時間達設定上限，就不允許繼續求解／評估；不能只是不開新迭代，卻讓當前工作為取得完整結果而延長。已開始的評估亦受此截止約束。
- 主張變化：`額度耗盡後等安全位置停止` → `安全一致性不足以約束超時` → `詢問上限意思` → `使用者選定不延長的截止語義`。反例被採納，非被駁倒；停止能力要求仍是待評估方案。
- 適用邊界：上限沿用 D37–D39 的求解額度，不是包含停機、必要狀態讀寫的端到端時間；未保存耗時回滾不變。此需求不等於現行實作已具可靠截止能力，也不承諾通用硬即時零誤差。不可中斷長步如何停止、如何保留一致狀態、是否採隔離／強制終止仍未定，本結論不授權實作強制終止。
- 未決結果處置：完整已驗證 checkpoint 解可否輸出、是否算 task 成功、無可用解如何處理，均未由本輪選擇確認；不因此授權更新整場正式成果。
- 待處理問題：由系統工程異端檢驗長步按時停止與保留可恢復進度如何兼容，再討論結果有效性與成功判定。
- 依據來源：使用者明確選擇截止時間；D35–D39 公開前提、質詢攻防與需求重整。LLM 一般背景知識開啟，未新增外部查證、檢查或修改程式；保留前文。

### D41｜停止實際工作，區分異常恢復、正常到限與合法無解

- 討論時間：2026-09-19 04:07:08 +08:00（完成仲裁後記錄）
- 狀態：依使用者持續討論、充分辯論後預設接受的授權確認；具體實作未驗證。
- 討論問題：按時停止如何兼容恢復，以及截止後只有舊 checkpoint 時能否完成 task。
- 決策過程：獨立工程異端提出框架停止等待、背景評估仍繼續並污染恢復狀態；騎士接受，停止契約涵蓋實際算法、評估及必要依賴，不只丟棄遲到結果。獨立實驗設計異端提出 60 分鐘截止、只剩 20 分鐘 checkpoint 與 D37 回滾的衝突；騎士接受，區分異常中斷與正常到限，並撤回沒有解就直接失敗的早期候選。仲裁判定原則可記錄，不記為反例被駁倒。
- 結論：
  1. 停止須真正涵蓋求解／評估及必要依賴，舊工作不得繼續推進或改寫接續狀態。丟棄結果只防污染，不滿足 D40；協作取消或受控工作生命週期是待驗證方案，不假定終止本機程序可停止遠端工作。
  2. 異常中斷按 D37 從成功保存的 checkpoint 恢復進度與額度；正常到限終止不自動回滾成待續跑。
  3. 正常完成須有當次額度／停止條件到達、相關工作確已停止及可驗證輸出狀態的證據，並成功持久保存完成記錄。只有舊 checkpoint 不能證明本次已完成；完成證據未保存便掉電，仍只能沿已有 checkpoint 接續。
  4. 舊 checkpoint 中完整已驗證的 best 可作已有 incumbent 輸出，但不能冒稱其進度為 60 分鐘；到限證據也不代表全程有效搜索，計費可能含恢復評估。
  5. 適用 solver／problem 的到限未找到解可為合法結果，不冒充已找到解，也不等同損壞或未驗證輸出。異常失敗仍不更新整場正式成果；全部 tasks 有合法完成結果才進入整場發布。
- 適用邊界：不保證截止瞬間尚未保存狀態完整，不把部分狀態兜底；可靠停止、輸出驗證與持久化載體待設計／驗證。D35–D40 與舊正式結果保護不變。
- 待處理問題：欠缺可靠停止／恢復能力的 solver 支援範圍，再討論保存頻率與持久化。
- 依據來源：使用者新的預設接受授權；D35–D40 與獨立角色公開条件推論。未外查或修改程式。

### D42｜基本註冊與模式支援分開，整場預檢與失效保護

- 討論時間：2026-09-19 04:10:30 +08:00
- 狀態：三輪獨立攻防後，依使用者預設接受授權確認；介面與實作未驗證。
- 討論問題：欠缺停止或恢復能力的 solver 如何保留註冊便利，又不暗中降低實驗要求。
- 決策過程：騎士初提基本註冊、迭代／嚴格時間／恢復分開宣告。質詢指出 solver 可取消但 problem 背景評估不可取消；採納為本次完整組合能力。工程異端指出運行取消失敗，標失敗不等於停止；採納失效保護。實驗設計異端指出已知後段 task 不支援，先跑半場仍無法更新；採納整場前置檢查。有效反例均非被駁倒。
- 結論：
  1. solver 可基本註冊；固定迭代、嚴格時間、checkpoint 恢復分開支援。能力須涵蓋本次 solver、problem 評估依賴及設定組合；要求不支援或未知時拒絕該模式，不默默降為軟時間或从頭重跑。
  2. experiment 求解開始前核對完整 task matrix 的能力条件，任何必要能力不支援／未知就拒絕該場並說明；跨 experiment 批量入口不因此一律拒絕其他獨立場次。預檢可讀資料，不把求解／評估藏成免費準備；不要求每次重測所有組合。
  3. 宣告信任、有限測試提供證據，不等於通用自動辨識或運行永不失效。啟動及運行仍须守住適用條件。
  4. 宣告支援卻取消失敗，明示本次截止違約、未停止工作及能力失效，拒絕發布新正式成果，保留舊成果與合法 checkpoint。確認停止及無污染前，不沿同一共享狀態恢復或自動重跑；停不了的外部工作明確交人工處置，相关組合須重新確認能力。
- 適用邊界：失效保護不能追回截止或保證停下任意外部工作；不因時間／恢復能力缺失一律禁止固定迭代或註冊。具體宣告、檢查、取消與隔離介面待映射實作。
- 待處理問題：保存頻率與成功持久化的最低契約，先檢視現行程式證據，不先選載體。
- 依據來源：使用者持續授權；D29、D35–D41 與獨立角色公開條件推論。未外查或修改程式。

### D43｜安全點請求保存，checkpoint 與完成結果各自一致提交

- 討論時間：2026-09-19 04:13:44 +08:00
- 狀態：三輪独立攻防後，依持續授權確認原則；載體及耐久性未驗證。
- 討論問題：保存頻率如何設定，什麼才算保存成功，保存是否影響公平。
- 決策過程：騎士提出可配置間隔、安全點截取、成功寫入才算保存。質詢提出覆寫舊算法狀態後 RNG 寫入失敗，latest 未改仍混版；採納不能改舊已提交資料。工程異端提出 completed 先寫、結果失敗造成跳過；採納完成結果一致提交。實驗設計異端提出並行大型保存干擾其他 task 的時間搜尋量；採納比較執行條件要求。反例均被採納，不記為駁倒。
- 結論：
  1. 保存間隔只提出請求，在 solver 一致安全點截取；例第 10 秒请求、第 12 秒才到安全點便於 12 秒截取。不因間隔要求混存不同時刻，不能保證不可中斷工作下的最長保存間隔；具體預設值稍後決定。
  2. 新 checkpoint 必須是完整必要狀態／依賴、RNG、進度及預算的同一保存單位，驗證提交成功才切換 latest。新保存不得破壞舊已提交內容，失敗仍可恢复舊版；引用切換本身不證明斷電安全。
  3. repeat／task 完成即及時持久保存，不等整場發布。task 身份／固定設定對應、有效結果或合法無解、必要驗證與終止證據、completed 作為同一完整單位提交；未提交不能跳過，已提交优先舊 checkpoint，同 task 只計一次，不必另保存完整終止 solver 快照。
  4. 排除自身保存時間不保證不干擾他 task。嚴格時間品質比較採經驗證的資源隔離條件或序列執行以避免同場互擾，不以文件說明代替驗證；平行吞吐仍支援，結論對應實際安排。固定工作量品質不必同速度，但加時間上限的组合仍受此問題影響。安排納入實際設定，不要求全面環境快照或絕對獨占硬體；外部負載限制須坦承。
- 適用邊界：需測試各寫入／提交階段中斷與保存失敗；本題不證明耐久性、停止能力或公平性已實作。載體、接口與預設頻率未選，D35–D42 不變。
- 程式證據：本次已讀 simulator/core.py 的集中組成結果、machine/core.py 的一次 solve worker 路徑、engine/models.py 的現有 task／結果模型、tools/show.py 的逐 variant 清空寫入、rng/context.py 與 factory.py。所讀路徑不足以證明上述契約；未聲稱全專案沒有其他恢復功能。
- 待處理問題：SQLite 與檔案載體選型，準備現行完成保存腳本及官方交易證據；再討論設定／task 身份／RNG 映射、結果發布與實作驗證計畫。
- 依據來源：使用者持續授權；K1 本討論、K2 本專案局部程式及角色條件推論、一般持久化背景。未外查或修改程式。

### D44｜本機 SQLite 作交易權威，同步保存與一致匯出

- 討論時間：2026-09-19 04:16:54 +08:00
- 狀態：三輪獨立攻防後依持續授權確認載體選擇與原則；部署／耐久性未驗證。
- 討論問題：SQLite 或檔案何者承擔恢復與完成結果的權威，以及外部匯出如何避免混版。
- 決策過程：騎士提出本機 SQLite 保存設定、進度、checkpoint 及結果，完整單位以同一事務提交，檔案作分析匯出。質詢提出提交後 ACK 遺失；補以資料庫提交為事實、操作身份查詢及冪等重試。工程異端提出排隊的可變物件晚序列化混進度；採納初版同步保存。實驗設計異端提出新設定與舊 CSV 混配；採納自包含一致匯出契約。反例被回答或採納，不宣稱程式已驗證。
- 結論：
  1. 初版選本機 SQLite 作設定、進度、checkpoint 與完成結果的交易權威，必要 payload 與狀態在同一 DB 事務提交，不先採資料庫成功標記加外部未提交 payload 的雙載體裂縫。不是自動具備 solver checkpoint，也不宣稱必然較快。
  2. saved 以完整資料庫提交為準，ACK 僅為通知；結果未知時按執行／task／保存操作身份查詢，已提交接受、未提交才重試。重試須冪等，不新增重複完成或令 latest 倒退；仍先確認舊工作停止。
  3. 初版在安全點凍結必要依賴，生成不引用可變 solver 物件的獨立同點 payload，序列化、提交確認或查詢釐清後再推進，不先加入延遲序列化佇列。不推進 RNG，不假定 deepcopy 對任何 state 均正確；純保存沿 D38 排除、實際評估仍扣額度。
  4. 匯出從固定已提交正式快照產生自包含包，包含同一 attempt 的設定、結果及預期 task 集合。外部讀取須確認完整與對應，不只相信 done 字樣；CSV 可為派生視圖，不任意跨版本搭配設定。
- 官方證據：SQLite [Atomic Commit](https://www.sqlite.org/atomiccommit.html) 支持事務原子提交但依賴儲存假設；[WAL](https://www.sqlite.org/wal.html) 說明同時單一寫者及本機共享條件；[synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous) 說明 WAL FULL 提交同步與 NORMAL 的耐久性差異（本次查詢 2026-09-19）。本地 WAL＋FULL 是部署候選，須核對儲存位置與實際設定，非無條件斷電安全。
- 程式参考：tools/mkp_item_eval_experiment.py 所讀 run_experiment 以 JSONL 追加完成 row、flush 並按 dataset／problem／variant／seed 跳過已有結果，可参考 task 完成續跑；不足以證明完整設定匹配、task 內恢復或耐久性。
- 適用邊界：大型 payload 優化、每場／全工作台 DB 粒度、具体格式與健康檢查仍未定；不保存算法快照或增加全面環境記錄。匯出失敗與正式發布關係另題明定，不將其默認當執行失敗或已發布成功。
- 待處理問題：整場正式發布與匯出失敗的交易邊界，維持失敗保舊；再談 DB 粒度、身份／RNG 映射與實作計畫。
- 依據來源：持續授權、K1 D35–D43、K2 所讀局部程式、K3 上述官方頁與條件推論。僅修改討論文件，未實作或測試 SQLite。

### D45｜必需分析包就緒才整場發布，準備與清理不破壞舊版

- 討論時間：2026-09-19 04:19:46 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；檔案持久化協議與讀者協調未驗證。
- 討論問題：匯出失敗是否阻止整場發布，如何保留舊成果及供外部 AI 分析。
- 決策過程：騎士提出全部 task 完成後必需包先就緒，才切 DB 正式引用。質詢提出同路徑覆寫舊包、準備中斷破舊成果；採納新 attempt 獨立包。工程異端提出未正式的 ready 包被清理後切引用；採納 prepared 保護與串行生命周期。實驗設計異端提出二進位解雖完整却 AI 不可讀；採納公開可讀分析表示。均採納非駁倒。
- 結論：
  1. 計算完成不等於正式發布。全部 tasks 有合法持久完成結果、必需分析包完整驗證且持久可讀後，才以同 DB 事務切換正式 attempt 與包引用。必需輸出失敗保留舊正式成果及舊包；新完成資料留存供重試輸出，不重跑求解。
  2. 新包準備不得覆寫舊正式包；讀者沿正式引用取得包，不假裝固定路徑多檔覆寫是原子發布。切換前暫存新舊两份，非永久歷史，亦不需要反覆搬動大量檔案。這是對先前簡單清空重寫偏好的修正：保舊保障需要最小的新舊重疊。
  3. prepared 包受保護，發布與清理由同 experiment 受控擁有者序列處理；清理認領後不能再發布。只有確認放棄或已被取代、且無正式或使用引用的包可回收；崩潰狀態未知先留存，不猜刪。
  4. 必需包是可讀分析輸出，含實際設定、task 身份／seed／人工 solver_version、停止原因、已耗預算、目標值及可行性／驗證或合法無解。解按 problem 公共格式呈現，如二元向量或路徑索引，保全數值型別與精度；二進位內部 checkpoint 不代替結果。具體序列化規則待定。
  5. CSV 預設派生、可重試，不自動為發布必要項；使用者明確要求某格式必需時，也須就緒才能發布，不偷偷降級。
- 適用邊界：不宣稱 DB 與檔案跨載體自動原子；包就緒順序、同步、讀者使用保護、清理中斷需故障測試。正式包讀取不要求 AI 取得算法 source；不新增時間模式標籤或全面環境快照。D35–D44 不變，對舊偏好的修正保留脈絡不回改前文。
- 待處理問題：單一工作台 DB 或每 experiment DB；再收斂身份／RNG、具体資料契約、CLI 與實作驗證計畫。
- 依據來源：使用者持續授權；K1 D06–D08、D29、D35–D44、K2 tools/show.py 局部覆寫窗口與角色條件推論。未修改程式。

### D46｜每 experiment 一庫，唯一執行擁有者與完整管理目錄

- 討論時間：2026-09-19 04:22:40 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；身份生成與操作實作未驗證。
- 討論問題：DB 粒度、同名並行發布、搬移範圍與跨場證據辨認。
- 決策過程：初提每 experiment 一庫、同名 attempts 同庫。質詢提出舊 A 遲完成覆新 B；採納同場唯一有效擁有者。工程異端提出即使乾淨搬 DB，外部包未搬仍不可讀；採納完整管理目錄。實驗設計異端提出同名舊新版包被當新增 repeats；採納包內來源及替代關係。反例採納非駁倒。
- 結論：
  1. 每 experiment 一個本機 SQLite，該場 attempts 共存庫內；不按 attempt 分庫，不先建全工作台共用庫。場內發布同事務、跨場分析外置，不需跨庫共同提交；不同庫仍可爭磁碟，不等於效能隔離。
  2. 同場同時只有一個有效執行擁有者及 active attempt；新請求遇舊工作未停止則拒絕並說明，不自動終止舊作業。跨程序排他及失效世代檢查，失權者不得遲到發布。舊正式成果可讀、其他場可並行。
  3. 完整儲存單位是受管目錄，含 DB、必要日誌與受保護包，採目錄內相對引用。初版只支援停止執行／清理、結束讀取、正常關閉後搬完整單位，不承諾線上搬庫或跨裝置直接續跑；分析可獨立取自包含包。
  4. 包內攜带持久 experiment／attempt 身份、group key、repeat 序號、實際 seed 及取代的正式 attempt。名稱不跨 output root 自動判為同一身份，生成機制另定。外部分析明選 attempt，同名新版不是新增 repeat；同 seed 的算法配對可合法，不按 seed 全面去重，也不將重跑自然當獨立樣本。
- 官方邊界：SQLite [WAL 文件](https://www.sqlite.org/wal.html#the_wal_file) 說明 WAL 為持久狀態，不任意丟棄或單搬 DB（本次查詢 2026-09-19）；[Backup API](https://www.sqlite.org/backup.html) 僅為後續一致備份参考，不因此新增線上備份功能。搬移與擁有權未實作驗證。
- 待處理問題：experiment／attempt 身份生成與同名定位，接著 task／RNG 映射。
- 依據來源：持續授權、K1 D41–D45、K2 現有 experiment 輸出層級、K3 官方文件與條件推論。僅修改討論文件。

### D47｜先鎖目錄建立身份，run 與明指 attempt 的 resume 分開

- 討論時間：2026-09-19 04:25:33 +08:00
- 狀態：三輪獨立攻防後依持續授權確認產品範圍；鎖與身份建立未實作驗證。
- 討論問題：持久身份如何產生、同名更新如何定位、續跑如何不選錯原執行。
- 決策過程：初提 output_root／安全 experiment_name 定位目錄、内部 UUID 與事務 attempt 序號。質詢提出副本同 UUID 分別取得本地鎖；採納非全域唯一保障、異地副本只讀。工程異端提出首次各自 UUID 各自鎖、同目錄分裂；採納先固定目錄鎖。實驗設計異端提出 resume 意圖明確但多個未完 attempt 對象不明；採納明指序號與恢復資格。反例採納非駁倒。
- 結論：
  1. output_root 加通過路徑安全檢查的 experiment_name 定位受管目錄；危險或衝突名稱拒絕，不自動修字撞名。首次生成並保存内部 UUID，名称不是跨目錄身份。
  2. 正規化管理目錄的固定鎖入口先於 UUID；取得排他權後，唯一 metadata 在事務中讀取／建立，後來者沿用已提交身份。鎖檔不得任意刪除重建；attempt 遞增序號在所有權及完整設定檢查後事務分配，失敗不留半套 metadata。
  3. 保存原註冊實體目錄，執行時核對正規化位置，別名指向同目錄共用所有權。複製至不同位置預設唯讀分析；另建新身份採配置全重跑、不继承 active checkpoint。不是全域副本偵測，不防人工改 metadata；靜止搬資料不承諾搬後續跑，執行設定路徑改動無安全例外。
  4. run 明確新建 attempt，同設定也可重跑；resume 必須明指目前可恢復的未完成 attempt 序號，不默選 latest。新執行接管後舊 attempt 不再續跑／發布；不要求无限歷史。
  5. resume 沿保存最終設定及 task 映射。若另提供設定檔，按 D33 比較，不同則拒絕 resume 並提示新跑，不自動啟動另一實驗。completed 僅讀取／匯出仍保留成果，不當新測量。
- 適用邊界：目前所讀 ExperimentSpec／RunTask 只用名稱及參數索引等，未證明以上身份機制；初建目錄競爭、鎖檔別名、失權與恢復資格需驗證。未修改程式。
- 待處理問題：task 身份／RNG 映射，以现行 seeding 程式為證據收斂。
- 依據來源：持續授權、K1 D32–D46、K2 局部模型與角色條件推論。

### D48｜task 身份與配對 seed 分開，完整 RNG 適配與恢復入口

- 討論時間：2026-09-19 04:28:44 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；適配與測試尚未執行。
- 討論問題：派生 seed、task 身份、隨機流及 checkpoint 恢復如何對應。
- 決策過程：初提保留 v2 problem／repeat 配對策略、事前保存映射。質詢提出不同 repeat 撞 seed；採納預檢拒絕。工程異端以恢復入口再執行 eager default 抽樣指出保存不等載入正確；採納入口與適配驗證。實驗設計異端指出新算法多抽一次後路徑分歧、单 seed 勝出不證穩定改善；採納比較說明。反例採納非駁倒。
- 結論：
  1. task 執行身份包含 experiment／attempt／group 與 problem／repeat，與 RNG 指派分開。初版保留現有 v2 由 base seed、problem type、dataset、problem id、repeat 派生，不混 worker、attempt、solver_version 或 group。跨算法／參數組同 problem／repeat 配對，使用各自獨立 RNG 物件。
  2. 啟動前保存實際 task seed 對應與策略版本；恢復讀保存映射與全部當前 RNG state，不重新派生或只設起始 seed。子流按邏輯組件而非 worker/thread 編號辨認，實際適配须驗證。
  3. 預設派生中不同 problem／repeat 邏輯位置得到同 seed，拒絕並指出衝突，不偷偷重映射；跨組配對不算衝突。人工明定 seed 列表可刻意重複，信任使用者，但不當自然獨立觀測。無碰撞也非統計獨立證明。
  4. 新執行初始化與恢復入口分開；恢復必要 state 後不再播種或執行額外推進主 RNG 的初始化。各實際 Python／Numba／子元件隨機流须支援取得／恢復 state，以短段候選、評估、進度／預算及段末所有流狀態對照驗證。未知不宣稱支援恢復，基本迭代不因此全禁；不靜默換 RNG，軌跡改動由使用者維護版本。
  5. 說明文件界定同 seed 是可重複配對起始安排，不保證算法全程抽樣同步或消除噪音。單 seed 勝出不足證穩定改善，跨 problem／seed、控制預算及起始資源的判斷交外部分析。
- 程式證據：rng/seeding.py v2 為 blake2b 派生再限制整數空間；strategy.py 有預設及顯式 repeat 列表；machine/core.py 各 task 建 generator。所讀 BSMA.py、BSCASMA.py、BSMA_numba.py 片段仍用 np.random／seed，Numba 主迴圈另設 seed；solve 的 config.get("run_seed", rng.integers(...)) 即使已有 seed 仍計算預設抽樣，是未來適配須處理的入口行為，不宣稱已有恢復 bug。
- 驗證狀態：讀過 tests/test_rng.py、test_simulator_batch.py 部分回歸／順序案例；嘗試 python3 -m pytest 未能執行，系統缺 pytest、專案無 .venv。無通過證據，未安裝或改程式。
- 待處理問題：solver／problem 保存、恢復與停止介面的整體設計，接著資料／CLI／遷移與驗收 gate。
- 依據來源：持續授權、K1 D35–D47、K2 上述讀取與命令證據、角色條件推論；未新增外部框架主張。

### D49｜可選 task session，額度內驗證與完整最佳解交付

- 討論時間：2026-09-19 04:31:47 +08:00
- 狀態：三輪獨立攻防後依持續授權確認接口意圖；具體簽名及能力未實作驗證。
- 討論問題：保留方便註冊，如何擴充原生 solver／problem 的恢復與嚴格停止。
- 決策過程：初提保留 solve、可選 session 初始化／恢復／受控推進／安全保存／有效輸出。質詢提出截止前解尚未驗證、再真評估會超時；採納額度內驗證。工程異端提出迫停 worker 私有 best 尚未完整交付；採納完整結果訊息。實驗設計異端提出不同報告頻率造成同搜尋品質呈現不同；採納正式時間比較的一致交付契約。反例採納非駁倒。
- 結論：
  1. 保留基本 solve／builder；進階功能由可選 task session／adapter 提供，不要求所有舊 solver 一次改寫，也不自動將 oneshot／Numba 記憶體 dump 當恢復能力。候選方法分開 initialize、restore、受控 advance、同點 snapshot、已驗證 outcome。
  2. session 管算法、相關 RNG 與必要依賴；problem 管驗證、公共解表示及有狀態依賴的保存／重建；controller 管計費、停止確認、生命週期與持久化，solver 不自己寫 SQL。每 task 獨立 session，不暗中共用可變 state。
  3. 真實目標及可行性驗證在求解額度內完成，維護已驗證 incumbent；截止後只能檢查結構／保存完整性，不能免費重評估。到限未找到已驗證解可依契約合法終止，不作不可行證明；無效搜尋候選不自動算系統故障，驗證機制异常須明示。
  4. controller 只接收完整不可變結果訊息，含 task、擁有權世代、序號與驗證證據；半截 IPC 不接受。截止後可用已完整交付的最佳已知解或有效 checkpoint 結果，不保證取得 worker 最後私有 best，不再補真評估。
  5. 正式時間比較每次形成完整已驗證新 incumbent 即完整交付、確認 controller 接收後再推進；不是每次改進寫完整 DB checkpoint。純交付處理排除計費，等待期間不得免費搜尋；實評估仍扣。不能遵守一致交付契約的 adapter 不接受此比較，legacy 整套接口結果不可冒稱純搜尋優劣。
- 適用邊界：停止須涵蓋所有真計算依賴；有界協作或全生命週期受控隔離須測試，不承諾零延遲／最後解零遺失。K2 所讀 registry 僅 oneshot solve；Problem ABC 是 fitness／constraints／validate，ProblemTypeSpec 是 loader／SHM 等，需新增可選接口但未修改。
- 待處理問題：執行控制設定及有效輸出資料契約，再收斂 CLI／遷移與驗收 gate。
- 依據來源：持續授權、K1 D36–D48、K2 solver/registry.py、problem/interface.py、problem/registry.py 與角色條件推論；未外查或實作。

### D50｜雙上限、單一計時軸、實際輸入核對與完整結果分母

- 討論時間：2026-09-19 04:35:23 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；schema 與計時未實作驗證。
- 討論問題：控制設定、同一實際輸入續跑、有效可讀結果的最小契約。
- 決策過程：初提統一雙上限、計時與結果欄位。質詢提出同 problem 路徑但檔案已變；採納實際輸入指紋。工程異端提出 advance 4 秒含評估 3 秒被扣 7 秒；採納區段聯集。實驗設計異端提出只匯出有解列導致平均偏差；採納每 task 完整記錄。均採納非駁倒。
- 結論：
  1. 正規化控制含可省略的 max_iterations／max_seconds，至少一個，任一先到即停止。前者非 bool 正整數，後者有限正數；舊單一 stop_condition 格式經適配正規化，不為比較強轉算法參數。iteration 按 solver 定義完成才計，evaluation 另計。
  2. 每 task 單一 monotonic 奈秒時間軸，計費區段取聯集，不累加巢狀或平行執行緒時長；advance 4 秒內含評估 3 秒只扣 4 秒。全部求解／評估靜止才排除純保存、傳輸或載入；階段切換先結算，checkpoint／終止存同值，限制判定前不四捨五入。
  3. checkpoint 預設每 60 秒提出安全點保存請求，可明確設定，非最長間隔保證；改配置依 D32–D35 新 attempt。
  4. loader 對實際載入的 problem／必要外部起點數值及結構產生規範化身份／指紋，每份輸入每 attempt 保存一次、tasks 引用，resume 重載比較；不同拒絕續跑，提示新執行全重跑。不靠重驗舊解修補；相關型別、shape、dtype、順序保留，不雜湊 YAML 排版。
  5. 可讀結果含 schema_version、task／seed／人工版本、結果種類、公共解與保全型別精度的目標、可行性／驗證、迭代／評估計數、求解秒數及停止原因。正式包每預期 task 恰一筆合法完成，保留合法 notfound：空解／目標、未知可行性與停止原因，不作不可行證明。
  6. error 留進度／診斷，不算合法完成，阻止整場發布；不刪未找到解的列、不把 null／NaN 改成零。NaN 等是否符合目標规范须明確，無依據不宣告有效。統計分析仍外置。
- 主張修正邊界：輸入指紋是對先前避免過量逐次 hash 的局部新增，限恢復相容證據；不擴成 source／全部環境 hash，manual solver_version 信任不變。hash 非数学零碰撞／隱藏依賴自動偵測，loader 明確覆蓋範圍需實作。
- 程式證據：所讀 SolverConfigLoader 只有單一 max_iterations／max_seconds；SolverConfigsSnapshot 保存副本；CLI 一次批次完成才寫 show；ResultEntry 未帶公共解，SolveResult 目前 best_solution 非可選。上述規格需遷移，未修改。
- 待處理問題：CLI 與舊流程遷移；實作前稽核仍須涵蓋 D27 已接受的研究關係與可選軌跡，不因近期聚焦恢復而漏掉。
- 依據來源：持續授權、K1 D31–D49、K2 tools/solver_config_loader.py、engine/configs.py、cli/run/support.py、tools/stat.py／models 與角色條件推論。

### D51｜純模擬操作、發布重試與明確匯出來源

- 討論時間：2026-09-19 04:40:44 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；未實作。
- 討論問題：新跑、續跑、發布／匯出如何不混淆，以及舊 seed 流程如何保留。
- 決策過程：騎士提獨立純模擬入口。質詢以 A 有 checkpoint、B 接管後失敗測試恢復資格，依 D47 拒絕復活 A。工程異端提出舊 publish 檢查跨接管重試；採納交易內重核。實驗異端提出完成但未發布的結果被 AI 當正式版；採納明確來源及匯出時身份。
- 結論：
  1. 候選入口 simulate start／resume --attempt N／status／export／publish --attempt N；名稱待實施計畫固定。start 新 attempt 全重跑；resume 指定目前有資格的未完成 attempt、使用保存設定，配置不同拒絕。接管後舊 attempt 不因新 attempt 失敗恢復資格；status 顯示資格，不只 checkpoint 存在。
  2. publish 重試完成但未發布的產出，不重新求解；正式引用切換的同一 DB 交易重新核對當下發布資格、有效 owner fence／世代、完整結果及受保護 ready 包的歸屬。任一不符不切換，保留當下 official；舊檢查或包就緒都不能授權切換。
  3. export 明選 official 快照或指定 attempt，不能以最大序號猜正式結果。包 manifest 表達來源身份、匯出當下的發布狀態與當時 official；完整未發布成果可探索分析，但不宣稱取代正式版。局部診斷另類呈現，不混入完整結果包。
  4. 舊 cli.exp seed 收集優化器及 cli.replay accepted seed 重跑保留原語意，不冒稱 checkpoint 恢復；舊文本結果不能直接當可恢復斷點。批量啟動各 experiment 獨立發布，非跨實驗原子批次。
- 程式證據：cli/exp/main.py 註冊 evaluator 後 experiment.run；cli/replay/main.py 讀 seed_bank、配置與 accepted entries，重新執行後 write_simulator_result，不是恢復執行狀態。僅讀取未修改。
- 待處理問題：補 D27 的研究關係／可選軌跡契約，然後實作前完整稽核與分段驗證計畫。
- 依據來源：K1 D31–D50、K2 上述 CLI 檔案、三輪角色條件推論；無外部事實缺口。

### D52｜研究宣告與可選軌跡，不把標籤當證明

- 討論時間：2026-09-19 04:43:09 +08:00
- 狀態：三輪獨立攻防後依持續授權確認；補齊既有 D27，未實作。
- 討論問題：研究關係如何保留，達標／收斂觀測如何不誤讀、不在恢復後混入失落分支。
- 決策過程：開場最小研究標註與固定成果引用。質詢提出同時達標但交付時間不同；採納產生且驗證時座標與首次觀測邊界。工程異端提出回滾事件再次浮現；採納事件不獨立於 checkpoint 提交。實驗異端提出調參用過的 seeds 改標 confirmation；採納人工宣告不認證獨立性。
- 結論：
  1. 可選研究設定含 stage（探索／確認，細用途可另描述）、factors（改動與預期固定条件）、固定 experiment／attempt／task 引用、comparison_group、split 宣告。分組及 split 指向實際 problem 身份與 repeat／seed 對應，不只集名；引用不隨 official 移動，舊證據若已清理不可由標註補回。
  2. stage／factor／split 表達人工研究意圖，不自動證明公平、holdout 獨立、因果或改善；未知保留，不追蹤全部調參史。人工 solver_version 信任不變，統計／製圖／調參仍外置。
  3. convergence／target-hitting 可選，只取已驗證觀測，不額外抽 RNG；真評估仍計費。目標及採樣設定啟動前保存；事件坐標用產生且完成驗證時累計求解 budget、iteration、evaluation，不用 controller 接收時間替代。
  4. 完整監測相關有效觀測才支持實際首次達標；採樣只能稱首次觀測達標，不能推測遺漏事件。不同 solver 不默認同密度；新 incumbent 的完整同步交付仍遵 D49。
  5. 首版事件不獨立持久化：安全點將新增事件、seq／cursor、首次達標狀態與 checkpoint 同交易提交；正常終止將尾段事件與完成證據同交易提交。重試冪等，resume 沿保存 cursor，未提交尾段隨進度一起丟棄，不能按當前時間暫藏再復活。
- 適用邊界：controller 已接收 incumbent 不等於軌跡已 durable；可能損失最後未保存觀測，符合 D37 回滾。標註不是自動統計認證，固定引用不是永久舊成果保留政策。
- 待處理問題：實作前稽核具体資料／監測介面、目標定義、需求覆蓋、程式落點與分段驗證 gate；不修改程式。
- 依據來源：K1 D25–D27、D36–D51 及角色條件推論；本題無新增外查。

### D53｜實作前計畫、出生納管與時間比較交付驗收

- 討論時間：2026-09-19 04:49:28 +08:00
- 狀態：三輪獨立攻防及獨立神諭核驗後依持續授權確認；僅規劃，不代表能力已成立。
- 討論問題：既有需求如何增量落地，是否仍有阻止進入實作的設計缺口。
- 決策過程：騎士提沿用既有 registry／problem／RNG，新增 planning／session／controller／store／export，逐段驗收。質詢指出 controller 消失仍有孤兒工作，承認單鎖／fence 不夠。工程異端指出 spawn 後補登記漏窗口；撤回逐 PID 清單完整證明，改啟動前納管。神諭核對 Linux 官方條件。實驗異端指出停止驗收不足以支持正式時間比較；採納交付／ACK 專用對照。
- 結論：
  1. implementation-plan.md 定義資料契約、SQLite 表族／交易、可選 session、CLI 入口、發布／清理與 P0–P8 小步驗證；本次不改程式。先建測試 baseline，再逐單元修改、針對驗證、檢查證據及回報，未驗證組合不開能力。
  2. 首版本機 Linux cgroup v2 為停止 scope 候選：先持久 unique never-reused intent，再建立 scope；launcher 阻塞，歸屬／有效 owner／權限核對後才放行算法及依賴。子程序在 scope 內出生納管，不靠事後補清單；worker 不獲遷出權限，父死晚放行亦驗收。
  3. 接管核持久 scope／啟動身份，確認整個受管工作及必要依賴停止、禁止舊 launcher 再放行，才新求解／resume。unknown 拒絕、待人工，不猜 controller 消失等於停止。外 daemon／GPU／remote 不自動由本機 scope 覆蓋。
  4. P2 驗收 intent／建立／blocked launch／納管／放行各窗口崩潰、孤兒與遷出；P5 另驗 ACK 延遲、半截 IPC、亂序／重送、截止交錯，只完整有效訊息、無遲到成果，等待時所有真求解／評估靜止，含初始化／首次驗證／首次 incumbent。未通過不宣稱正式時間比較，私有未交付 best 不補猜。
- 外查邊界：K4 官方 fork 繼承、子樹 kill、populated=0 可支持 scope 方案；事後移動父不補既有子。delegation／實際部署權限待驗，freeze 可耗時，無物理零延遲保證。這不放寬 D40、不把越界冒充完成。
- 實作證據邊界：目前 python 不存在、python3 缺 pytest，無成功執行測試；diff --check 只驗文件。算法選讀不算所有 solver 完整狀態稽核；Numba 適配另段逐組驗收，不永久撤回需求。
- 待處理問題：最後文檔／需求覆蓋及矛盾檢查，確認後停在實作前一步。
- 依據來源：K1 D27–D52；K2 implementation-plan.md 草稿及既有程式；K4 [Linux Kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)，獨立神諭核驗；角色條件推論。

### D54｜新舊輸出共存，檢查與變更不能有空窗

- 討論時間：2026-09-19 04:54:42 +08:00
- 狀態：最終查漏後三輪獨立攻防，依持續授權確認；只修計畫。
- 討論問題：legacy show 的 rmtree 如何不刪新資料庫／正式包，自訂路徑及別名如何處理。
- 決策過程：開場獨立 namespace＋持久 marker＋重疊檢查。質詢提出檢查後其他程序新建受管下級；採納共同結構鎖。工程異端提出別名檢查 A 後改指 B；撤回 realpath 足夠，收窄初版寫路由。實驗異端確認拒絕不代表授權換路、搬移或重跑，未另造衝突。
- 結論：
  1. 初版共同物理 domain 為 output；受管 namespace 為 .optiforge-workbench/experiments/NAME，固定結構鎖 .optiforge-structure.lock。域根／鎖／namespace 保留，root／experiment marker 持久。legacy 不得刪寫受管範圍，也不得刪包含受管下級的祖先。
  2. managed 建立、legacy exp／replay／show reset、匯出目的地準備、受控 mkdir／rename／GC delete 共用結構鎖，在鎖內核對及變更；求解不持鎖。鎖檔不刪換，不建全域 experiment 索引。
  3. custom／nested 寫 root 僅同既定 domain，不能動態另建嵌套協調域。初版破壞性寫路由拒絕 symlink，操作用已確認物理路由；保留 canonical 身份讀取，但明確收窄 D47 別名寫入及任意目的地支援。非重疊合法預設舊路徑不改。
  4. 拒絕在建 attempt／求解前，actual_config、checkpoint、official 不變；不自動換 root、搬移或新跑。使用者處理路徑仍按 D32 的 start／resume 規則。需要外部分析可自行複製完整可讀包。
- 邊界與驗收：所有受支援 writer 須合作同鎖，P6 雙進程建立／reset 競態、祖先重疊、別名／身份變化及拒絕無副作用，P7 覆盖舊入口。未採 fd 綁定，不能宣稱抵抗不合作程序任意替換祖先或必然偵測所有外部競態。
- 待處理問題：最後文件需求覆蓋 gate，停在編碼前。
- 依據來源：K1 D32、D45–D53；K2 tools/show.py 精確輸出路徑及 _reset_variant_output_dir，implementation-plan.md；角色條件推論，無新增外查。

### D55｜最後文件 gate 通過，停在實作前一步

- 討論時間：2026-09-19 04:56:08 +08:00
- 狀態：終局文件稽核完成；不是新一輪攻防、不是功能驗收。
- 核對問題：需求／程式落點／資料契約／小步驗證計畫是否完整，是否仍有必須先決定的產品設計。
- 決策過程：工程與實驗設計角色各自完整核對 D27–D53 及計畫，均 PASS-with-runtime-gates；root 最後查漏形成 D54，立即記錄並同步計畫。仲裁賢者完整讀取最終計畫及 D53–D54，未發現阻礙定稿的未決設計，文件 gate 通過。
- 結論：混合搭建最小實驗控制／證據層，沿用現有可驗證底層；保存結果與實際設定、原 task 內恢復、公平優先、整場正式發布，分析／調參外置。implementation-plan.md 包含需求覆蓋索引、資料／session／交易／CLI／輸出保護及 P0–P8 驗證 gate。
- 證據：git diff --check 通過；僅 discuss.md 修改及 implementation-plan.md 新增，未修改程式。原前 868 行 SHA-256 仍為 e98fcea0a3efcc4367ebe2f345d00e30a60e3646330ae48041c90289678b49a1，與先前核對一致，原討論未重寫。每題即記，時間與演化保留。
- 未驗證事項：pytest 環境缺失，無成功執行 baseline；實際儲存耐久性、scope／停止／交付競爭、所有 solver／Numba 狀態與部署能力待各段證據，不能把文件通過說成功能已成立。
- 停點：本次討論目標完成，停在編碼前。不建環境、不裝依賴、不啟動模擬、不改程式；P0 環境與 baseline 須後續執行授權。
- 依據來源：K1 D27–D54、K2 最終計畫及唯讀檢查、獨立工程／實驗設計／仲裁公開結論。

### D56｜每個 repeat 的 seed 指派採嚴格模式，明確區分派生與人工指定

- 討論時間：2026-09-19 15:54:36 +08:00
- 狀態：三輪獨立攻防後確認；只形成設定契約，未修改程式。
- 討論問題：實驗人員如何明確定義每個 repeat 的算法起始 seed，同時兼顧多 problem、參數組配對、續跑及設定易讀性。
- 現況證據：現行 DerivedPerProblemSeedStrategy 依 base seed、problem type、dataset、problem id、repeat index 穩定派生；SharedRepeatSeedListStrategy 可讓各 problem 沿 repeat index 共用一維 seed list。Machine 在排程前建立 task_seed，worker 依 task_seed 建立 RNG 並寫入 run_seed；通用 CLI 目前只暴露 base seed。測試覆蓋 seed assignment 的順序／參數／solver 無關及 sequential／batch seed 相同，未證明所有 solver 完整軌跡相同。
- 決策過程：開場提派生與 explicit 兩模式。質詢指出一維 explicit list 在多 problem 下會把共享 seed 當成默認研究語意；採納 scope 必須明示。工程異端指出 explicit 模式殘留 base seed 造成設定與實際 map 矛盾；採納嚴格 tagged union。實驗異端指出相同 seed 不等於相同隨機擾動或獨立樣本；採納更精確命名與主張邊界。
- 結論：
  1. seed 是 experiment execution config，不放進 solver YAML；算法參數與實驗隨機設計分開。
  2. seed_plan 為嚴格 tagged union。derived_base_seed 只接受 base seed 與派生策略版本，依 problem×repeat 派生。explicit_repeat_seed_assignment 強制 scope=all_problems 或 per_problem，前者提供 repeat seed list，後者提供完整 problem→repeat seed lists。
  3. 多 problem 時不接受未標 scope 的一維列表。各模式的非作用欄位即使是 null 也拒絕；不能暗定優先順序。repeat_count 由 experiment 明確提供，seed lists 只驗證長度，不反向推斷。
  4. 啟動前保存 canonical effective seed config、策略種類／版本及展開後完整 problem×repeat→task_seed map。resume 使用保存 map，不重新派生；mode、有效欄位、版本或 map 任一不同，依 D32 開新 attempt。
  5. 同一 experiment 的所有參數組預設使用同一 task seed map以支援按 seed 配對，但每個 task／參數組建立獨立 RNG 物件；不按 group key 偷偷派生。若未來需要每組不同 seeds，必須另立明確模式。
  6. 相同 seed 只證明可重現的起始指派並允許按 seed 對照，不證明不同算法有相同隨機路徑、不同 problems 為獨立樣本、已使用 common random numbers、消除噪聲或比較公平。manifest 保存 assignment mode／scope／version／actual map，不產生 fair／independent 等認證標籤，研究解釋外置。
- 主張變化：derived＋一維 explicit 默認跨 problems 共用 → 承認維度歧義，加入明確 shared／per-problem scope → 嚴格排除 inactive 欄位 → 將 shared 命名收縮為 explicit seed assignment，避免誤稱共享完整擾動。
- 適用邊界：本題只確定 seed assignment 及設定語意；worker 排程是否影響所有 RNG 消耗與完整結果，仍須獨立討論及逐 solver 驗證。現有 SharedRepeatSeedListStrategy 可作能力基礎，但通用設定尚未接線。
- 待處理問題：併發下完整 RNG 軌跡的契約；之後將定案 schema 範例同步到 implementation-plan.md。
- 依據來源：K1 D01–D03、D29、D32–D33、D48；K2 rng/strategy.py、rng/seeding.py、machine/core.py、cli/run、solver設定與相關測試；三輪角色條件推論，無外查。

### D57｜併發 seed 指派不等於完整重現，fresh run 與 resume 分開驗收

- 討論時間：2026-09-19 23:11:26 +08:00
- 狀態：三輪獨立攻防後確認；發現現行缺陷及驗證缺口，未修改程式、未執行 pytest。
- 討論問題：worker 數量、task 排程及 worker 重用是否會改變 RNG 消耗與完整結果，何時才可承諾精確重現。
- 現況證據：worker_count>1 使用 spawn ProcessPool；task seed 在提交前固定，worker 為每 task deepcopy config、設定 run_seed、建立 Generator 及 solver，完成順序經 task key 歸位。但 MachinePoolSession._group_tasks_by_machine 現行對每 task 連續 append 兩次，可能重複提交並由同 key 覆蓋；大量 solver 使用 process-global np.random 及 Numba RNG，且多處 config.get(run_seed, rng.integers(...)) 即使已有 run_seed 仍 eager 消耗 Generator。既有 batch 測試只比 seed assignment；solver same-seed 測試多只比最終解／目標，未涵蓋跨 worker、順序、恢復與完整軌跡。
- 決策過程：開場提 schedule-independent fixed-work capability。質詢指出 ACK 遺失重算可能產出完全相同結果，駁倒物理 exactly-once；改為至多一個有效 scope及一份權威結果。工程異端以 A checkpoint→B 污染 global RNG→A 恢復挑戰 fresh-run 測試；採納 fresh 與 resume 能力分開。實驗異端以迭代／時間 OR 上限在不同排程下先後改變，駁倒事後依 stop reason 宣稱 exact；採納啟動前資格判定。
- 結論：
  1. 只有通過 fresh_run_schedule_independent 的 solver／problem／dependencies／完整設定組合，才可承諾同裝置 fixed-work 下，每 task 的決定性結果不受 worker 數、提交／完成順序及同批其他 tasks 影響。時間模式不由此能力涵蓋。
  2. 不承諾 task 物理上恰好計算一次。提交狀態未知先依 operation ID 查權威 store；確認未提交且舊 execution scope 已停止後，才以新 generation 重算。任何時刻至多一個有效 scope，最終一份 committed outcome；保存重派世代／原因，禁止舊世代遲到寫入。固定工作結果相同不代表沒有重算。
  3. fresh_run_schedule_independent 與 resume_schedule_independent 為兩個能力。後者要求 checkpoint 涵蓋所有實用 task-local／global RNG、solver state、可變 problem 依賴及邏輯進度；恢復前完整還原，advance 期間 process 由該 task 獨占。fresh 通過不能推出 resume 通過。
  4. Python global np.random 只有完整 state adapter 及穿插驗證通過才可支援 resume。Numba 內部 RNG 若仍不透明，該組合不得宣稱 resume，須先改成顯式 state／可停止分塊。eager default 額外抽樣必須修正並加入回歸測試。
  5. 最小恢復對照包括：A uninterrupted；A checkpoint→同 worker 執行 B→同 worker 恢復 A；A checkpoint→fresh worker 恢復 A。逐步核對候選／事件、outcome、iteration／evaluation、所有 RNG 段末邏輯 state及可變 problem 依賴，不能只比 final objective。
  6. exact fixed-work 資格在啟動前依設定及能力決定。只要包含 max_seconds、其他 wall-clock 條件或非確定外部到達順序會影響終止，就不屬 exact；即使某次 OR 上限恰好以 iterations 結束，也不能事後改標 exact。合格停止決策只能依可保存的邏輯 state，例如 iteration、evaluation、已驗證值及確定性規則。
  7. 精確等價的觀測範圍包括 typed solution／objective、feasibility、result kind、iteration／evaluation、確定性 stop reason、事件邏輯座標，以及 RNG／checkpoint 的邏輯 state；不含 runtime、solve_ns、牆鐘 timestamp、訊息抵達順序或 PID。浮點位元等價只在已驗證的同裝置／數值環境與確定性設定範圍承諾，否則不能稱 exact。
  8. worker_count 變更仍依 D32 建立新 attempt；跨 worker capability 測試是對結果不變性的驗收，不構成以新 worker 設定 resume 舊 attempt 的例外。
- 主張變化：seed assignment 相同即可不受併發影響 → 增加完整狀態／軌跡及排程驗收 → 撤回 physical exactly-once → fresh 與 resume 分層 → exact 從事後結果判定改為啟動前固定邏輯工作資格。
- 適用邊界：process 隔離降低同時共享 global RNG 的風險，但不證明 worker 重用、隱藏 RNG、可變 problem、數值依賴或 checkpoint 已安全。時間停止可保存相同 seed 及實際結果，仍不保證重播相同結果。
- 待處理問題：以具體 YAML 收斂 experiment／seed_plan／solver params／worker／stop control 的分檔與錯誤訊息；同步 D56–D57 到 implementation-plan.md。
- 依據來源：K1 D01–D05、D32、D36–D40、D43–D44、D48、D53、D56；K2 machine/core.py、solver RNG 搜尋及相關測試；三輪角色條件推論，無新增外查。

### D58｜新增純模擬 experiment YAML，以穩定 group key 引用現有 solver 設定

- 討論時間：2026-09-19 23:45:24 +08:00
- 狀態：更正錯誤前提後重新完成三輪獨立攻防；設定分工及預覽契約確認，未修改程式。
- 討論問題：現行純模擬只有 solver YAML＋CLI 參數，是否新增 experiment YAML，以及如何避免兩份設定衝突並保持實驗友善。
- 前提更正：先前候選錯把 experiment YAML 說成既有設定並提議把完整算法參數移入其中；使用者指出現況不是兩份設定。該候選撤回。cli/exp/exp_cfg.yaml 屬舊 seed 收集／篩選流程，不是本題純模擬設定。
- 決策過程：重新比較 A 擴充 solver YAML放全部實驗控制、B experiment YAML複製完整 params、C experiment YAML只引用 solver 參數組；推薦 C。質詢指出 index 引用遇重排會選錯組；採納 managed 流程必須用來源內穩定 key。工程異端提出 controller 保存 0.1 但 worker 重讀已改為 0.2 的 TOCTOU；採納一次解析及 immutable AttemptPlan。實驗異端指出只看 group refs 無法在啟動前審查；採納唯讀 resolved plan 預覽與 digest 核對。
- 結論：
  1. 正式新增純模擬 experiment YAML。solver YAML 是 solver 類別、capabilities 及完整算法參數組的唯一來源；experiment YAML 是 experiment identity、人工 solver_version、problems、選定 group keys、repeat、worker、limits、checkpoint、seed_plan及可選研究設定的唯一來源。experiment 不複製或局部覆寫算法 params。
  2. managed 跨檔引用要求 solver YAML 每個參數組有明確、場內唯一且跨 start 穩定的 group key；禁止以列表 index 或只存在某 attempt 的自動 key 引用。相同 key 的完整 params 改變會形成新 attempt，不會改指另一組。
  3. D30–D31 的自動 key 收縮為單次凍結執行內部識別，不足以作跨檔、跨 start 引用。legacy CLI 繼續支援 --set index；遷移工具只能產生 key／轉換預覽，須使用者確認並寫回 solver YAML，不能自動改檔。
  4. managed CLI 只接受動作、experiment config 路徑及身份／安全核對參數，不接受 worker、seed、limit 或算法參數等臨時 execution overrides。需要改執行內容先改 YAML，再 start，避免第二權威來源。
  5. controller 對當次來源內容只做一次權威讀取，解析、型別化、能力／輸入驗證並展開 group map、seed map及 task matrix，建立 immutable AttemptPlan；完整 plan及 input identity先提交成功才派工。worker 只消費 plan task payload和凍結 problem pack／引用，不按來源路徑或 group key重讀 YAML；路徑只是 provenance。
  6. 大型 problem／SHM pack須對應保存的 input identity／fingerprint且執行期間不可變。worker重啟依 committed plan重建；需要重載輸入時按 D50 核對，不同則拒絕。來源在 plan提交後修改只影響下一次 start；resume沿保存 plan。
  7. 新增唯讀 simulate plan --config FILE，輸出 resolved完整參數組、problem／seed map、task matrix、limits及 canonical plan digest；不建立 experiment、attempt或DB紀錄，僅供人工／AI審查，不是執行證據。
  8. start會重新解析當下來源、提交真正 AttemptPlan並輸出／保存 digest。可選 --expect-plan-digest DIGEST只作啟動前一致性核對；不一致即拒絕，不能用 preview覆寫設定。執行後的權威證據是 committed AttemptPlan及結果包，不是原始 YAML或舊preview。
- 主張變化：假設既有兩份設定並搬移params（撤回） → 比較新增設定的三方案 → 採引用而非複製 → index引用退守為stable key → 路徑引用退守為一次解析的 frozen plan → 增加非權威預覽解決跨檔可審查性。
- 適用邊界：具體欄位名稱及 codec仍可在實作前 schema一致性稽核調整，但不得改變責任分工、嚴格 seed union、無 execution override及 committed plan權威。舊 run／exp／replay語意保留。
- 待處理問題：將 D56–D58 最小 YAML範例、plan命令及驗收項目同步 implementation-plan.md，做唯讀一致性檢查。
- 依據來源：K1 D21–D22、D30–D33、D45、D50–D51、D56–D57；K2 configs/solvers、cli/run、cli/exp現況；三輪角色條件推論，無新增外查。

### D59｜D56–D58 設定與 RNG 契約一致性複核通過

- 討論時間：2026-09-19 23:48:04 +08:00
- 狀態：兩名獨立角色唯讀稽核均為 PASS-with-runtime-gates；未修改程式、未執行測試。
- 稽核問題：新增 experiment YAML、stable group key、strict seed_plan、immutable AttemptPlan、plan preview及 fresh／resume能力分層，是否與 D32、D50、legacy CLI及實作計畫衝突。
- 工程稽核：managed stable key與legacy index分流清楚；resume --config只核對、不覆寫；start一次解析、提交plan後worker不重讀；preview非權威、expect digest只作前置條件；seed union及省略limit欄位一致。未發現設計BLOCK。
- 實驗稽核：repeat及seed scope可明確表達，完整map／actual params保存；相同seed不誤認公平／獨立／CRN；含max_seconds於啟動前排除exact；fresh、resume及位元等價邊界分明。未發現設計BLOCK。
- 結論：D56–D58可納入實作前計畫，不需新增產品決策。最小YAML與plan命令已同步 implementation-plan.md；具體loader、digest codec及錯誤字串在P1落地，但不能改變已確認語意。
- 待驗證事項：legacy loader遷移、global／Numba RNG、problem pack指紋、digest穩定性、worker/order/subset及穿插恢復對照，依P1／P3／P7／P8取得實測證據。pytest仍未執行，文件PASS不等於能力成立。
- 停點：本次補充討論完成，仍停在實作前；不建環境、不改程式。
- 依據來源：K1 D56–D58、K2更新後implementation-plan.md；獨立工程及實驗設計唯讀稽核。

### D60｜SQLite 管控制帳本，checkpoint 統一使用外部不可變 object

- 討論時間：2026-09-20 17:28:54 +08:00
- 狀態：使用者確認儲存媒介方向已收斂並授權寫入文件；具體 schema、checkpoint adapter、RNG、備份與回收尚未完成，未授權繼續修改程式。
- 討論問題：在 task 數量可由數十至數萬的前提下，執行狀態、checkpoint、設定及分析輸出應放 SQLite 或文本，以及是否應依 payload 大小分流。
- 討論過程：原 D44 採「必要 checkpoint payload 與狀態同一 SQLite 事務」以避免雙載體裂縫。本輪重新比較純文本、全入 SQLite、依大小分流及單一外部 object 方案；質詢、捍衛及仲裁均判定按大小分流會引入兩套發布、恢復、備份、清理與診斷規則，且閾值是隱藏環境策略。SQLite 官方文件確認單寫者／多讀者、本機 WAL 與交易適合控制帳本；數萬筆 metadata 不構成引擎容量問題，BLOB 內外置效能仍依硬體／檔案系統而定，不以舊測試的 100 KB 當架構分界。
- 結論：
  1. 每 experiment 保留一個本機 SQLite 作為執行控制帳本，管理 experiment／attempt／task、狀態轉移、擁有權、冪等操作、checkpoint descriptor、latest／official 與發布關係。SQLite 不是人與 Codex 的主要閱讀介面。
  2. v1 的所有 checkpoint payload，不論大小，統一儲存為受管目錄中的外部不可變、以 digest 辨識的 object；SQLite 只存 descriptor、digest、byte size、format／storage version、安全相對路徑、task／attempt 關聯及 latest 指標。v1 不存 SQLite BLOB payload，不按大小自動分流。
  3. `storage_kind` 是版本化格式欄位，v1 唯一合法值為 `external_object_v1`；未知值拒絕，不把預留欄位誤稱已實作多 backend。未來只能依 checkpoint 大小／頻率、WAL 佔用、寫入延遲與備份時間的實測結果新增版本化 backend，不得暗中切換。
  4. object 的最低發布順序為：staging 完整寫入與計算 digest → file flush／fsync 與大小核對 → 同一本機檔案系統內 no-clobber 原子發布 → directory fsync → SQLite 事務登記 descriptor 與切換 latest。任一前置步驟失敗不得登記 descriptor；DB 失敗只能留下未引用 orphan。
  5. 恢復前必須重新驗證 object 存在性、大小、digest 與格式版本。DB 有 descriptor 不等於 payload 當下必然健康；缺失／損壞必須明示拒絕，不靜默回退或重跑。v1 的 orphan 只列報告，不自動刪除。
  6. 設定、resolved plan、status／diagnostic 及發布成果維持 YAML／JSON／JSONL／CSV 等可讀介面；人與 Codex 不需直接解析 SQLite 或 checkpoint payload。分析包繼續是由已提交權威狀態產生的不可變投影，不反過來成為執行真相。
  7. 完整儲存單位仍是 D46 的受管目錄；WAL 模式下不可只複製主 DB。執行中備份應使用 SQLite snapshot／Backup API 並連同被引用 objects；目前仍只承諾停止執行、正常關閉後搬移完整目錄，不新增熱搬移。
- 對舊決策的修正：本決策明確取代 D44 結論 1 中「必要 checkpoint payload 與狀態在同一 DB 事務」及將 checkpoint 完整 envelope 存於 SQLite 的部分。D44 的 SQLite 控制權威、事務狀態、ACK 失落查詢與冪等規則繼續有效；D45 可讀分析包及 D46 每 experiment 一庫／完整管理目錄也繼續有效。
- 適用邊界：這是 v1 儲存架構決策，不等於 checkpoint 功能已實作或已驗證斷電安全。格式 envelope、adapter mandatory state、全域 barrier、RNG registry、event durable 邊界、一致備份、retention／GC 及支援 OS／檔案系統矩陣仍須逐題收斂與驗收。
- 官方依據：SQLite [Isolation](https://www.sqlite.org/isolation.html)、[Appropriate Uses](https://www.sqlite.org/whentouse.html)、[Limits](https://www.sqlite.org/limits.html)、[Internal Versus External BLOBs](https://www.sqlite.org/intern-v-extern-blob.html)、[WAL](https://www.sqlite.org/wal.html)、[WAL-mode File Format](https://www.sqlite.org/walformat.html) 及 [Backup API](https://www.sqlite.org/backup.html)；BLOB 效能數字只作環境依賴的測試參考，不當通用分界。

### D61｜Managed RNG 採雙 profile、顯式 PCG32 state 與版本化 stream topology

- 討論時間：2026-09-20 19:42:21 +08:00
- 狀態：核心、初始化 ABI 及 stream topology 已由使用者逐項確認；僅為設計契約。官方 PCG reference 已做原始碼對照，但本專案尚未建立 runtime golden vectors、Python／JIT conformance 或 checkpoint 驗收，未修改正式程式。
- 討論問題：現行 NumPy global／Numba RNG 與 `rng_demo.py` 候選之間如何取捨，並建立不隱藏 seed 派生、可列舉、可恢復、Python／JIT 可逐步對照的 managed RNG。
- 現況證據：現行 framework 為 task 建立 `default_rng`，但多數 solver 再用 `run_seed` 重設 process-global `np.random` 或 Numba 內部 RNG；`config.get("run_seed", rng.integers(...))` 因 eager default 即使已有 `run_seed` 仍額外推進 Generator。`note/improve/rng_demo.py` 的 PCG32 seed／step 公式經逐行對照與 PCG 官方 minimal C source 一致，但 demo 的 time seed、單 u32 float 與 bound 邊界不是 managed 契約。
- 決策過程：先否決用一套新 RNG 透明覆寫舊結果，採 legacy／managed 雙 profile。隨後收縮雙 HMAC 設計：所有 stream 仍必須先經 semantic HMAC 得到 StreamSeed256，但 PCG adapter 直接以固定 byte ABI 切片，不再做第二層 HMAC。再以 endian／bit 遮罩歧義、共用 mutable stream 與過度拆分為反例，收斂為 task-local registry、stable stochastic feature stream 及版本化 solver RNG contract。
- 結論：
  1. RNG profile 固定分為 `legacy-v2` 與 `managed-pcg32-v1`。Legacy 保留現行 seed／global NumPy／Numba 行為及舊 replay 語意，不宣稱 exact checkpoint；managed 是新實驗語意，不保證與 legacy bitwise 同軌。Profile 改變必須形成新 resolved plan，不得於 resume 時替換。
  2. Managed core 固定為 `pcg32-xsh-rr-64-32-v1`：unsigned 64-bit LCG multiplier `6364136223846793005`，以更新前 `oldstate` 做 XSH RR output transform，先截成 `uint32` 再 rotate，並以 modulo `2^64` 更新 state。Mutable state 為每 stream 獨立的 `state + odd increment`；managed 禁止 `seed=None`、時間 seed、global fallback 及未登記 RNG。
  3. PCG 初始化先令 `state=0`、`increment=(seq63<<1)|1`，丟棄一次 step，加入 `seed64` 後再丟棄一次 step；兩次 warm-up 都不能交給 solver。官方 `initstate=42, initseq=54` 的前六個 outputs `a15c02b7, 7b47f409, ba1d3330, 83d2f293, bfa4784b, cbed606e` 作為外部錨點；仍需實際驗證 Python、JIT、overflow、rotate 及 restore。
  4. 所有 managed stream 必須由已解析 task root、單一 owner、版本化 semantic path 及 typed dynamic keys 經 canonical、domain-separated HMAC-SHA-256 形成 32-byte StreamSeed256。設定可表達 base／repeat／task root intent，但一般設定不得直接注入最終 StreamSeed256／PCG state；只有 test／golden vector 及 checkpoint restore 可走明確例外入口。確切 canonical root／message codec 仍需另行定版。
  5. PCG adapter 固定為 `pcg32-init-split127-be-v1`：`S[0:8]` 以 big-endian 讀為 `seed64`；`S[8:16]` 以 big-endian 讀為 `seq_word64`，`seq63=seq_word64 & 0x7fff_ffff_ffff_ffff`，`increment=(seq63<<1)|1`；`S[16:32]` 不進 PCG backend，但完整 StreamSeed256 仍保存於 manifest。Byte order、slice、mask、increment 或 seeding 順序改變都必須建新 adapter ID。
  6. Manifest 不得把 task root、StreamSeed256 與 backend tuple 混稱「seed」；須保存 semantic identity、initialization class、完整 StreamSeed256、`seed64`、raw `seq_word64`、effective `seq63`、increment、core／adapter／contract versions。不同 initialization classes 在同 experiment 內得到相同 `seq63` 時於第一次 draw 前 fail closed；不以 nonce、建立順序或重抽隱藏碰撞。
  7. 每個 runtime task 擁有自己的 registry，每條 stream 只有一個 owner，不共用 mutable object。Stream 按 stable stochastic feature 劃分，不是每個 helper／draw 一條，也不是 solver 全部共用一條。Solver init／search、problem、evaluator、simulation 及 analysis 不默認共用 stream；無隨機行為的 component 宣告 zero-stream，日後偷用 RNG 視為 contract violation。
  8. Dynamic stream 只能來自事前宣告的 template 及穩定 business identity，例如 evaluation／scenario／replicate ID；禁止使用 worker、thread、attempt、arrival／completion order、registry size 或 parent RNG 的 `spawn_next()`。Resolved plan 保存 static topology 及 templates；runtime event 留 dynamic identity／owner／lifecycle evidence；checkpoint 只保存仍可能繼續 draw 的 live／resume-relevant streams 完整 state。Closed 是不可逆 terminal 狀態；closed ephemeral stream不必保存 mutable state，但 checkpoint／restore 必須保留其完整 semantic identity 與 owner 作 tombstone，恢復後同一 identity 不得重新 materialize、重新初始化或再次 draw。
  9. Parameter groups 沿 D56 不加入 task root；同 problem／repeat 可取得相同 initial material，但各自擁有獨立 state，只稱 `paired stream initialization`。不同 solver 採使用者選定的 B：namespace 用 `solver-contract/<rng_contract_id>/<feature>`；預設各 solver 有自己的版本化 contract ID，只有明示共用 ID 且通過相同 draw-order／golden-vector conformance 的實作才能配對初始化。Draw contract 改變必須升版；即使配對也不宣稱 CRN、公平或統計獨立。
  10. Fresh retry 依原 resolved identities 建立全新的初始 states，attempt number 不參與 HMAC；resume 必須恢復 checkpoint 內 registry 與每條 live stream 的 `state + increment`，不重新 seed、不重跑 warm-up，也不共用 state array。Freeze 期間禁止 draw 與建新 stream；unknown／missing／extra stream、owner 或 version 不符均 fail closed。
- 主張變化：現行 RNG 加強即可恢復 → legacy／managed 分流；StreamSeed256 再雙 HMAC 映射 backend → semantic HMAC 後以永久 byte ABI 直接切片；每 task 單 stream 或每 draw 拆 stream → stable feature stream；同 seed 代表公平／CRN → 只保證可稽核的 paired initialization。
- 適用邊界：本題固定 managed RNG 核心、初始化及所有權，不等於已實作、通過統計測試、支援 solver checkpoint 或證明公平／獨立。官方 PCG 對照只支持 core／seeding 語意，不驗證本專案 Seed256 layout、HMAC codec、高階 primitive 或 checkpoint envelope。
- 待驗證事項：canonical HMAC root／message codec、layout 與 official vectors；Python／JIT unsigned overflow、rotate 與 state codec；seq63 collision index；registry lifecycle／freeze／restore；task 交錯、worker 數、fresh retry 與 resume 的逐步對照。
- 依據來源：K1 D01–D03、D36–D38、D48、D56–D60；K2 `note/improve/rng_demo.py`、solver／machine／rng 相關程式及測試的唯讀盤點；PCG 官方 [minimal C implementation](https://github.com/imneme/pcg-c-basic/blob/master/pcg_basic.c) 與 [basic usage](https://www.pcg-random.org/using-pcg-c-basic.html)；多輪角色攻防及使用者選擇。

### D62｜Managed RNG primitive suite 覆蓋現有正式 solver 抽樣語意

- 討論時間：2026-09-20 19:42:21 +08:00
- 狀態：現有正式 solver 的 RNG call shape 已唯讀盤點並映射到第一批 primitive；契約已由使用者逐項批准，但尚未實作、不宣稱 Python／JIT 已一致。
- 討論問題：如何把現有 `random`、`uniform`、`randint`、`choice`、`shuffle` 及 CTF threshold 比較收旂為少量、可版本化、draw consumption 明確且能逐位測試的 managed API。
- 決策過程：以 32-bit uniform 對極小機率失真、Fisher–Yates 正反向都均勻但排列不同、ordered pair 的角色不可交換、categorical 尾格 fallback 可選到零權重、affine rounding 可回傳 high，以及 CTF threshold 可超出 `[0,1]` 為反例。通用名稱因此收縮成精確 state machine；不為未有 consumer 的 API 擴大 v1 surface。
- 結論：
  1. `next_u32_v1` 每次消耗一個 PCG32 output。`uniform_f64_53_v1` 固定消耗兩個 outputs：第一個取高 27 bits，第二個取高 26 bits，形成 `k/2^53`，輸出 `[0,1)` 的 53-bit grid。不以 demo 的單 u32 乘 `2^-32` 作通用 float64 uniform。
  2. `bernoulli_f64_strict_v1` 只接受 finite `p∈[0,1]`；合法呼叫固定先消耗一次 `uniform_f64_53_v1` 再做 `u<p`，包括 `p=0` 與 `p=1` 也不 short-circuit。超界、NaN 或 infinity 在 draw 前拒絕。
  3. CTF 等原始 threshold 另用 `uniform_f64_53_lt_threshold_v1`，接受任意 finite binary64 threshold，固定先消耗 uniform53 再做 strict `u<threshold`。`threshold<=0` 必假、`threshold>=1` 必真，但都仍消耗兩個 raw draws。使用者選定 B：NaN 與 `±Infinity` 在 draw 前 fail closed；RNG 層不 clamp CTF。
  4. `bounded_u32_v1(bound)` 使用版本化 threshold rejection 回傳 `[0,bound)`：在 uint32 語意下以 `threshold=(-bound) % bound`，拒絕 `raw<threshold`，接受後回傳 `raw%bound`。合法範圍是 `1<=bound<=2^32`。`bound=2^32` 明確特別處理為一次 `next_u32`，不先 cast 成 uint32；`bound=1` 也固定消耗一個 raw draw並回傳 0。其他 bound 每次 bounded call 固定為一個 API 操作，raw draw 數可因 rejection 變動。
  5. Shuffle 固定為 `shuffle/fisher-yates-desc-bounded-u32-v1`：完整預驗證後，對 `i=n-1...1` 依序做 `j=bounded_u32_v1(i+1)` 與 index swap。`n=0/1` 零 draw；`j==i` 仍已消耗該次 bounded call；重複值不影響 draw 數。V1 只提供 in-place API，接受具 exclusive ownership 的一維 C-contiguous writable 固定寬度 numeric／bool array，或滿足相同條件的 array view；copy API 延後。
  6. 使用者選定 A，v1 只提供 `sample_ordered_pair_distinct_excluding_u32_v1`：`3<=n<=2^32`、`excluded∈[0,n)`，固定以 bounds `n-1`、`n-2` 呼叫兩次 bounded；在壓縮 domain 先排除 first position，再將兩個 position 映回排除 current 的原 index domain。輸出 `(first,second)` 有序、互異且皆不等於 excluded；不做 pair-level rejection。未有正式 consumer 的一般 distinct-pair API 延後。
  7. `categorical_index_f64_weights_linear_v1` 只接受一維 C-contiguous `float64` weights，每項 finite、非負且至少一個正值。驗證時以 binary64 left-to-right scalar 累加得到 `total`，禁止 fastmath、parallel sum 或重排；正權重被累加完全吞掉或 total overflow 時於 draw 前拒絕。`n>=2` 固定消耗一次 uniform53，計算 `target=RN_f64(u*total)`，再由 0 開始以相同 left-to-right binary64 順序重新累加 cumulative，回傳第一個滿足 strict `target<cumulative` 的 index；不得改成先正規化 cumulative 再與 `u` 比較。Fallback 只能回傳最後正權重 index。使用者選定 A：`n=1` 驗證通過後零 draw 回傳 0。CDF／batch／alias table 及 weighted-without-replacement 延後。
  8. `uniform_affine_f64_53_half_open_v1` 對 finite `low<high` 固定分離執行 `span=RN_f64(high-low)`、`scaled=RN_f64(span*u)`、`x=RN_f64(low+scaled)`，禁止 FMA、fastmath、reassociation 與 extended-precision 改寫。若 `x>=high`，以 bit-defined `nextafter(high,toward=low)` 修正；若 `x<low`，夾回 low，保證 half-open。使用者選定 A：`low==high` 仍消耗一次 uniform53後回傳 low 原始 bits。NaN、infinity、`low>high` 或 span overflow 在 draw 前拒絕；支援環境不得啟用 FTZ／DAZ。
  9. 所有可預驗證的輸入、dtype、shape、ownership 或版本錯誤必須在第一個 draw 前 fail closed，RNG state 與輸入 buffer 不變。單一 primitive 是 checkpoint 的不可分割區間；safe point 只能在完整呼叫前或後，不以每步一 draw 推算 rejection 後 state。
  10. 唯讀覆蓋盤點顯示：現有正式 solver 的 random／uniform／randint／uniform choice／weighted choice／without-replacement pair／shuffle 及 CTF comparison 皆可映射到上述 API；正式 Simulator／experiment／evaluator 當前未發現額外分布抽樣。這只是 call-shape coverage，不代表 solver 已完成遷移，也不排除後續路徑審計找到隱藏 RNG。
- 主張變化：一個 Bernoulli 取代所有 `u<x` → strict probability 與 finite raw-threshold 分流；「Fisher–Yates」名稱即足夠 → 固定 descending state machine；用重抽取兩個 index → 固定兩次 bounded 的 compressed remapping；categorical 尾格兜底 → weights-only strict linear scan；base uniform half-open 就保證 affine half-open → 增加固定 endpoint correction。
- 適用邊界：這些 primitive 只保證明列的離散映射、錯誤時機及 draw contract，不宣稱不同 streams 統計獨立、結果公平、通用 CRN 或理想連續均勻。Solver 中 `sin`、`cos`、`tanh`、`log10` 等 libm 差異及浮點控制流仍可使軌跡分歧。
- 待驗證事項：每個 API 的 scripted 與 end-to-end PCG vectors；Python／JIT 的 raw outputs、rejection trace、index／swap trace、float bits 及最終 state；subnormal、signed zero、overflow、endpoint、zero weight、illegal-input zero-draw；每個正式 solver call site 完整接線後的 uninterrupted／resume 對照。
- 停點：D61–D62 只完成 managed RNG 設計文件；候選 P1 程式變更繼續凍結，不因本輪批准自動進入實作。
- 依據來源：K1 D48、D56–D61；K2 solver／tools／Simulator／experiment／evaluator 相關 RNG call sites 的唯讀盤點；Python 與 NumPy MT19937 公開 reference 用於 27＋26-bit float64 方法對照；多輪質詢／捍衛／仲裁及使用者選擇。

### D63｜TaskRoot／StreamSeed 採固定 OFRNGTLV codec 與完整正向 golden vectors

- 討論時間：2026-09-20 21:54:23 +08:00
- 狀態：欄位、byte order、HMAC 邊界與正向 vectors 經多輪質詢／捍衛／仲裁收斂；參考 encoder、獨立 Node encoder 與 OpenSSL HMAC 的結果一致。這是設計及驗收契約，尚未實作。
- 討論問題：如何讓 explicit／derived TaskRoot 與每條 StreamSeed 的來源完全可見、跨語言逐 byte 相同，並避免問題內容、root provenance、worker 或建立順序偷偷改變 RNG。
- 結論：
  1. Explicit task root 直接使用 `U256BE`：只接受非 bool 整數 `0 <= x < 2^256`，相同整數永遠得到相同 32 bytes；不再 HMAC。`root_class` 只作 manifest provenance，不進 stream message。Derived root 使用 `BaseSeed256=U256BE(base_seed)` 作 HMAC-SHA-256 key；problem content fingerprint 不進 root，只綁定 plan／task／resume，防止跨輸入恢復。相同 fingerprint 配不同 logical problem ID 只警告，不合併 identity。
  2. Canonical envelope 固定為 magic ASCII `OFRNGTLV`（hex `4f46524e47544c56`）、codec version `U16BE=1`、message kind `U16BE`（1=derived root、2=stream）、field count `U16BE`。每個 field 為 tag `U16BE`、type `U8`、payload length `U32BE`、payload；fields 必須嚴格遞增。Type IDs 固定 `ASCII=1`、`U64=2`、`PATH=3`、`DYN=4`。
  3. Derived schema 固定 tags：1 strategy ID、2 problem-seed-identity schema ID、3 problem type、4 optional dataset ID、5 problem ID、6 repeat index U64。TaskRoot256=`HMAC-SHA-256(BaseSeed256, complete derived envelope)`。Dataset absent 以整個 tag 省略表示，不以空字串替代。
  4. Stream schema 固定 tags：1 RNG contract ID、2 owner ID、3 semantic PATH、4 typed dynamic keys；DYN 即使為空仍存在並編碼 count 0。StreamSeed256=`HMAC-SHA-256(TaskRoot256, complete stream envelope)`。PATH 以 segment count 與各段長度編碼；DYN 以 contract template 順序編碼 name、subtype（1=U64、2=ASCII）與 value。Dynamic mapping 的來源插入順序不具語意。
  5. Stable ID 使用 case-sensitive regex `[A-Za-z0-9][A-Za-z0-9._-]*`。ABI 上限固定為 top fields 8、stable ID 255 bytes、PATH 32 segments、DYN 16 keys、field payload 16384 bytes、envelope 32768 bytes、nesting depth 1；在依宣告大小配置、HMAC 或 RNG 建立前驗證。
  6. 正向 golden set 固定 D0、D1、S0、path segmentation S1a／S1b、mixed-DYN S2、provenance-invariant S3 及 D1→S0 end-to-end。每筆都固定 semantic input、完整 preimage hex、byte length、key 與 expected digest；不得由 production encoder 自產 expected。獨立重算的 digest 依序為 `ed519cd704bfcf2ab0e07a5428aac8850eeba7d2db47bd65d82cad6e9fff7ac1`、`97b743e1159b05a8111fbfe0251be2ef5941989fee87ad8dc2dd6919fb1f0191`、`968ba887391f14a0cae0b4b941521dcd4d85ebbb9beeef2f68b8e0477c8302b1`、`9636c14739b483baade4617e2bda5b9e8687ef43860bd8ae805a26fdf44f9a2c`、`ce0266a854f0a8064beccb262e1a02733d014e35cb6f2a4f193c4af198dd4fa8`、`ddcae87720460dcd167ad255a51236aac3af1515e44c014c2c97ef5e65403492`、`242f5186c45226761dc8eb52455c09bed6a7bc39a30104a47ca8168c7b521f7d`、`fd2034a0b1cb0e467a16ad605d33c56a684fe24dabb926850ac52a8a8d9a7d96`。完整 fixtures 同步於 implementation-plan.md。
  7. 正向 vectors 使用獨立 test-only semantic registry，明列所支援的 strategy、identity schema，以及 `abc-v1` contract 的 owner、paths 與 DYN templates；它與 negative-only `empty-v1` fixture 分開，也都不是 production contract map。如此成功向量才能驗證完整 encoder→semantic validator→HMAC 路徑，而不只驗低階 bytes。
- 適用邊界：digest 相同證明固定 key／bytes 下的 HMAC 相同，不證明 production encoder、decoder、registry 或 solver 已接線；這些仍須 P1 以跨實作 vectors、round trip 與拒絕測試驗收。
- 依據來源：K1 D56–D62；既定使用者選擇；三輪角色攻防；本輪只讀 Python／Node／OpenSSL 交叉計算，未修改程式。

### D64｜非法 OFRNGTLV 採三階段拒絕；stream identity 必須非空，不相容資料暫停而非判壞

- 討論時間：2026-09-20 21:54:23 +08:00
- 狀態：質詢者、捍衛者與裁決者完成兩輪修正及逐 byte 重驗；G-N1～G-N7 全數 PASS。使用者批准非空 PATH 與 `blocked-incompatible` 生命週期；僅更新設計文件，未修改程式。
- 討論問題：raw codec 或 typed encoder 收到非法／不支援資料時，哪些結果必須跨 library、CLI、checkpoint 穩定，如何避免錯誤資料已進 HMAC、RNG 或留下部分狀態。
- 結論：
  1. Codec rejection 的不可分割 machine tuple 固定為 `(outcome=REJECTED, stage, code)`。`FRAMING` 管外層 bytes、安全邊界與上限，codes 為 `LIMIT_EXCEEDED`、`MALFORMED_ENVELOPE`、`UNSUPPORTED_CODEC`；`CANONICAL` 管唯一 schema、PATH／DYN 內部結構及 lexical rules，codes 為 `LIMIT_EXCEEDED`、`SCHEMA_VIOLATION`、`INVALID_VALUE`；`SEMANTIC` 管 registry／contract 能力，codes 為 `UNSUPPORTED_ID`、`CONTRACT_MISMATCH`。人類訊息、exception class、offset 及 stack trace 不屬 ABI。
  2. 固定安全優先序：先 header／magic、envelope size 與 top field-count caps；每個 field 先驗 outer length／cap／remaining bytes，再解 nested payload；PATH／DYN 先驗 nested count cap，再依 count 迴圈；canonical 全通過後先判 `UNSUPPORTED_ID`，只有 supported ID 才判 `CONTRACT_MISMATCH`。跨階段順序是契約，同階段任意 first-error 細節不是；多重缺陷一般測試不鎖人類訊息。
  3. 所有 `FRAMING`／`CANONICAL`／`SEMANTIC` rejection 都必須在 HMAC 前完成，不得建立／推進 RNG、註冊 stream 或留下 partial mutation。`digest absent` 不足以證明副作用不存在；以 HMAC spy、RNG factory spy 及 registry mutation assertions 分開驗證。
  4. HMAC provider 在合法輸入後故障不是 codec rejection，另列 operational `ERROR / DERIVATION_OPERATION / HMAC_PROVIDER_FAILURE`；此時 HMAC 可已呼叫，但 RNG factory 必須仍為零且不得留下半成品。
  5. Raw decoder 與 typed encoder 分開測試。Raw bytes 沒有 bool 概念，只驗 framing／canonical／semantic；bool 冒充 integer、負數、超界與錯誤 runtime type 屬 typed encoder。Golden 鎖跨實作完整 raw hex＋length＋expected tuple＋digest absent；完整規則排列放 unit tests，截斷／length／count 與資源界線放 fuzz／security，CLI／checkpoint／library 的同 tuple 與無副作用放 integration tests。
  6. 每條 stream 的 PATH 必須包含 `1..32` 個非空 stable-ID segments；不允許 `[]`。這些 segments 是開發者在 RNG contract 中宣告的穩定 stochastic-feature identity，不是使用者每次執行手動命名。不得另造 magic `root` 保留字；若 contract 使用 `root`，它只是普通且明確的 feature ID。DYN count 0 合法且 field 仍存在；dynamic key name 與 ASCII value 非空，U64 value 0 合法。
  7. 不支援的 codec version／message kind 或合法但不支援的 strategy／contract 都禁止 fallback、resume 與 RNG 建立；attempt 標為 `blocked-incompatible`，保留原始資料及診斷。安裝相容 reader／contract 後可重新驗證；不得標成資料損壞或永久 `failed`。真正 malformed／invalid／contract mismatch 仍按各自 tuple fail closed，是否可恢復由上層狀態規則判定。
  8. Test-only registry 只含 supported contract `empty-v1: owner=solver, path=[search], dynamic_keys=[]`；`ghost-v1` 是不在 supported set 的固定 negative sentinel，不得放入可執行 contract map。七組 negative goldens 對應：G-N1 `FRAMING/LIMIT_EXCEEDED`、G-N2 `FRAMING/MALFORMED_ENVELOPE`、G-N3 `FRAMING/UNSUPPORTED_CODEC`、G-N4 `CANONICAL/SCHEMA_VIOLATION`、G-N5 `CANONICAL/INVALID_VALUE`、G-N6 `SEMANTIC/UNSUPPORTED_ID`、G-N7 `SEMANTIC/CONTRACT_MISMATCH`；完整 bytes 同步於 implementation-plan.md。
- 決策演化：先提出未經團隊審查的四分類草案並撤回 → 質詢先界定 raw-byte 信任邊界與處理層次 → 第一版把 derivation failure 混入 rejection 且兩筆 fixture 有歧義 → 裁決退回 → 重畫三階段、重做 fixtures、逐 byte 重驗 → 使用者以白話例子理解並批准非空 feature identity 與不相容暫停。
- 適用邊界：checkpoint／manifest 是否實際儲存 raw OFRNGTLV 由其格式設計決定；只有真正接收 raw bytes 的持久化、IPC、匯入或 library decode 邊界才走 decoder。一般 YAML／CLI 不接受 raw TLV、hex preimage 或 final seed。
- 停點：本輪只收斂 codec 與錯誤生命週期；候選 P1 程式變更仍凍結，不自動進入實作。
- 依據來源：K1 D32、D50、D56–D63；兩輪 examiner／defender／moderator 公開結論、逐 byte fixture 複核及使用者最終選擇。
