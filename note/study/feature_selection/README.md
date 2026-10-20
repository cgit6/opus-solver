# 特徵選擇研究專案索引

從 `note/study/populationMetaHeuristic-20261018T082452Z-1-001.zip` 整理出 6 個特徵選擇相關專案與 1 份算法片段。共保留 134 個原始檔案，約 11.7 MiB，包含程式、資料集、論文、Notebook 與歷史結果。

本目錄目前是研究資料區，尚未接入本系統的問題／算法註冊。原始程式內容沒有修改，也沒有執行訓練或求解實驗；以下入口僅供閱讀定位，不代表已可直接執行。

## 專案與閱讀入口

| 專案 | 內容 | 閱讀入口 | 附帶資料與執行前注意事項 |
| --- | --- | --- | --- |
| [BPSOGWO-main](BPSOGWO-main/) | Python：BPSO、BGWO 與混合 BPSOGWO 特徵選擇 | [zoo.py](BPSOGWO-main/zoo.py)、[algorithm/BPSOGWO.py](BPSOGWO-main/algorithm/BPSOGWO.py) | 有 11 個資料集對應的主程式，但缺少程式引用的 `data/` 資料目錄及 `result/` 輸出目錄。 |
| [BPSOGWO-with-GA(Feature_select)](<BPSOGWO-with-GA(Feature_select)/>) | Python：混合 PSO／GWO，含 GA 操作 | [main_5050.py](<BPSOGWO-with-GA(Feature_select)/main_5050.py>)、[main_9010.py](<BPSOGWO-with-GA(Feature_select)/main_9010.py>)、[BHPSOGWO.py](<BPSOGWO-with-GA(Feature_select)/BHPSOGWO.py>) | 根目錄與 `18_data/` 各有 18 個 CSV，另有 4 個歷史結果 XLSX。`main_5050.py` 的資料路徑寫死為另一個資料夾名稱，執行前需另行處理。 |
| [Binary Optimizer／BPSO](Metaheuristic-Binary-Optimizer-for-Feature-Selection---BPSO-master/) | MATLAB：二元 PSO 特徵選擇範本 | [main.m](Metaheuristic-Binary-Optimizer-for-Feature-Selection---BPSO-master/main.m)、[ClassificationFunction.m](Metaheuristic-Binary-Optimizer-for-Feature-Selection---BPSO-master/ClassificationFunction.m) | 附 `wine.xlsx`，但程式仍有維度、上下界、資料檔名及欄位範圍等待填內容，不能視為完整可執行實驗。 |
| [modifiedACO-master](modifiedACO-master/) | Python：修改版二元蟻群與 DEAP GA 特徵選擇 | [mbaco.py](modifiedACO-master/mbaco.py)、[feature_selection_ga.py](modifiedACO-master/feature_selection_ga.py)、[fitness_function.py](modifiedACO-master/fitness_function.py) | 範例使用 scikit-learn 內建乳癌資料與 LinearSVC；GA 需 DEAP。`mbaco.py` 含頂層實驗程式，直接 import 也可能觸發執行。 |
| [qbso-fs-master](qbso-fs-master/) | Python：蜂群搜尋、強化學習與特徵選擇 | [main.py](qbso-fs-master/main.py)、[fs_problem.py](qbso-fs-master/fs_problem.py)（評分）、[swarm.py](qbso-fs-master/swarm.py)（搜尋） | 附 25 個 CSV、8 份 Notebook 及 [畢業論文](qbso-fs-master/thesis/engineering_grad_thesis.pdf)。原 `requirements.txt` 固定舊版套件，現代 Python 相容性尚未驗證。 |
| [SummerResearchDE-BPSO](SummerResearchDE-BPSO/) | Python：資料載入、切分與 population 的早期原型 | [src/Main.py](SummerResearchDE-BPSO/src/Main.py)、[src/DataManager.py](SummerResearchDE-BPSO/src/DataManager.py)、[src/Population.py](SummerResearchDE-BPSO/src/Population.py) | 附 1 個藥物資料 CSV。主程式含原作者路徑，且呼叫目前類別沒有實作的方法；特徵移除部分仍在註解中，不是完成的 DE／BPSO 求解器。 |

另保留 [fragments/DE/mmasdefs.py](fragments/DE/mmasdefs.py)：含 MMASDEFS、差分進化與特徵子集評估。它引用 `data_source` 及 Shuttle 資料載入函式，但整份來源壓縮包沒有附上 `data_source`，因此歸為不完整片段，不單獨當作完整專案。

## 整理方式

- 各專案保留自己的目錄、資料集、論文、歷史結果與原有授權檔；未把同名資料集合併。同名 CSV 不代表欄位、標籤或前處理方式相同。
- 僅將來源中重複包裝的 `qbso-fs-master/qbso-fs-master/` 縮為一層 `qbso-fs-master/`。
- 不搬入虛擬環境、Git 內部資料、Python 快取及 IDE 設定；這 6 個專案內共略過 16 個快取／IDE 檔案。
- 壓縮包內不相關的背包、TSP 與其他算法範例不放入本目錄。原始 ZIP 保留不動，沒有刪除其中任何內容。
- 沒有自動補資料、修改硬編碼路徑、安裝舊依賴或修補未完成程式，避免把整理工作變成算法修改。

## 已完成的核對

- 134 個原始檔案均與來源 ZIP 成員逐檔核對 CRC／SHA-256，內容一致。
- 38 個 Python 檔案通過語法編譯檢查；檢查未 import 或執行其程式。
- 8 份 Notebook 通過 JSON 結構檢查。

上述核對只確認整理完整性與基本語法，不代表依賴可安裝、程式能跑完，或歷史實驗結果可重現。

各檔案的來源路徑、大小、校驗值及排除清單見 [IMPORT_MANIFEST.json](IMPORT_MANIFEST.json)。
