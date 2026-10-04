# SCVRP 移植、題庫與驗證資料

本資料夾集中保存 SCVRP 移植盤點、效能改善規劃與本機找到的研究文件。

## 目前移植範圍

- `SCRP.rar` 內有 90 個不重複的 CVRPLIB `.vrp`；其中 7 題有 SCVRP
  fixed-route plans。
- 其中只有 7 個 base instance 具有 SCVRP fixed-route plans：
  `A-n32-k5`、`A-n48-k7`、`A-n64-k9`、`A-n80-k10`、
  `P-n16-k8`、`P-n19-k2`、`P-n23-k8`。
- 每個 base instance 各有 16 組 `(RouteCap, MaxTransfer)`，合計 112 個
  可直接形成的 SCVRP 問題設定。
- Archive 中有歷史 report/solution 的是 4 個 base instance、共 64 組設定：
  `A-n32-k5`、`P-n16-k8`、`P-n19-k2`、`P-n23-k8`。
- 112 組 raw inputs 均已保存於 `dataset/legacy_sa/instances/`，逐檔 hash
  與結構狀態記錄在 `dataset_manifest.json`。
- 其中 96 組原始結構完整；另外 16 組是四個 A 題的 `RouteCap=8`，原始
  fixed-route 各缺一位 customer。
- 歷史完整重播顯示舊 Windows C++ 當時將缺失 position 讀成 route owner 0；
  因此 16 組以明確標記的 legacy owner=0 相容層載入。112 組均已有 canonical
  YAML，但這不代表原始 Gurobi fixed-route 資料已被修好。詳見
  [validation_status.md](validation_status.md)。

先前的 seeds 1–10 長跑驗證仍是同一個問題設定的多 seed 驗證，不是跨題庫
驗證。跨題驗證命令已建立，但完整長測留給使用者自行啟動。

## 論文與文件

`SCRP.rar` 中沒有 PDF、DOC、TeX 或 BibTeX 論文；兩份 PPTX 已選擇性復原至
`results/`，並通過 archive CRC、檔案大小及 PPTX ZIP 完整性檢查：

| 檔案 | SHA-256 | 用途 |
|---|---|---|
| `主要流程(使用教學).pptx` | `7fe236b3fd98a1396f9d27170abdf0ee7cc40586930f9ea415e04161f919aed5` | 舊專案操作流程 |
| `P-n23-k8_RouteCap_2_MaxTransfer_1適應值圖.pptx` | `00af610994317f042011f5ac4115c31e3a9e32b45cfce344419d801dfce3e1b0` | 歷史結果圖 |

專案原有兩份 PDF，已複製到 `papers/`：

| 檔案 | SHA-256 | 初步分類 |
|---|---|---|
| `畢業論文.pdf` | `bfdb0af062d56ba7ec7f0cae0b5e444952706377a3b769f7861db1aeb4751f1d` | MKP／HSMSCA，非 SCVRP 專論 |
| `Complexity 1241051.pdf` | `33e556807aa7c436f2e0de40bea8e7b910fe63c12fe8afe3c85cf7ff908ab3d9` | MKP／HSMSCA，非 SCVRP 專論 |

這兩份文件保留作演算法與效能研究參考，但不能當作 SCVRP 原算法規格來源。

## 修改算法前的必要 gate

1. 盤點 archive 的 112 個 SCVRP inputs，保留 16 個缺 customer 的原始證據。
2. 對 96 個直接設定及 16 個 legacy-compatible 設定完成靜態驗證。
3. 對有歷史輸出的 64 組設定解析 report/solution，建立 oracle。
4. 至少對 7 個 base instance 各選代表設定，執行 CDELS／C++ oracle 流程差分。
5. 建立跨 instance、跨 seed 的效能與品質 baseline。
6. 完成上述 gate 後，才開始流程優化；Legacy bug 修正排在 Python 與 Numba
   優化完成之後。

詳細效能階段與驗證規則見 [performance_optimization_plan.md](performance_optimization_plan.md)。

## 題庫與驗證命令

以下命令都從 repository root 執行。盤點與靜態驗證不會啟動 solver：

```bash
.venv/bin/python -m mkp.tools.scvrp_dataset inventory
.venv/bin/python -m mkp.tools.scvrp_dataset static-validate
```

只查看短版跨題驗證計畫，不執行：

```bash
.venv/bin/python -m mkp.tools.scvrp_dataset validate-run \
  --seeds 1 \
  --iterations 111
```

自行啟動 112 個設定的短版 CDELS／C++ oracle 逐代比對：

```bash
.venv/bin/python -m mkp.tools.scvrp_dataset validate-run \
  --seeds 1 \
  --iterations 111 \
  --output output/scvrp-validation/all-112-short-cdels \
  --execute-expensive
```

完整 seeds 1–10、11,220 transitions 長測：

```bash
.venv/bin/python -m mkp.tools.scvrp_dataset validate-run \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --iterations 11220 \
  --output output/scvrp-validation/full-seeds-1-10 \
  --execute-expensive
```

每完成一個 task 就會同步追加到 `runs.jsonl`；相同命令與 output 可直接續跑。
可先加 `--max-new-runs 1` 驗證單一 task。若 seeds、iterations、config、
manifest 或 solver source 改變，既有 plan 會拒絕混用，必須使用新 output。
舊的 `output/scvrp-validation/all-112-short` 屬於移轉前的 solver contract，應保留
作歷史證據，但不能用來續跑 CDELS；請使用上面的新目錄。

`wall_runtime_seconds` 只作效能紀錄，不參與 exact comparison。Exact gate 比較
最終狀態、路線、轉移、objective、feasibility、溫度位元、RNG state/draw count，
以及每一代完整 canonical population trace。每列另存 `raw_objective`、
`legacy_penalty` 與 `legacy_search_score`；不可行解必須滿足
`legacy_search_score = raw_objective + 100`，可行解的 penalty 則為 0。
