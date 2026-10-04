# SCVRP 題庫與 exact validation 狀態

## 目前結論

- Archive 邏輯題庫：112 組（7 base instances × 16 組參數）。
- Raw inputs 已保存：112／112。
- 原始 fixed-route 完整：96／112。
- 使用明示 legacy owner=0 相容層：16／112。
- 已建立且可載入 YAML：112／112。
- Blocked：0／112。
- 完整跨題長測：尚未由 Codex 執行；依需求留給使用者手動啟動。

## CDELS 正式入口切換

- 正式 Engine solver ID：`cdels`。
- 正式演算法與 Engine adapter：`solver/CDELS.py`。
- 舊 Python core、local search、adapter 與 solver-side kernel wrapper 已移除。
- 封存 C++ 僅透過 `tools/scvrp_native_oracle.py` 作測試 oracle；正式 Engine
  import／求解不會載入它。
- 切換前已完成 seed 1、11,220 transitions 的舊 Python／CDELS 逐代回放，
  11,221 個世代完全一致，process trace SHA-256 為
  `2a6adf93d6f20b37fc18fbef1831dffa83a8c8b9d97b6edcf30cb44d6f07aa1e`。
- 切換後的單題、seed 1、1 transition CLI smoke test，CDELS 與 C++ oracle
  為 `exact_match`，objective 437、RNG state 2587854408、draw count 16073。

舊 `output/scvrp-validation/all-112-short` 屬於切換前 contract，不能續寫。
新的 112 題驗證必須使用不同 output 目錄，例如
`output/scvrp-validation/all-112-short-cdels`。

## 16 個原始資料異常與相容處理

四個 A 題在 `RouteCap=8`、`MaxTransfer=1..4` 時，fixed-route 檔各缺一位
customer：

| Base instance | 缺少 customer | Blocked 設定數 |
|---|---:|---:|
| `A-n32-k5` | 2 | 4 |
| `A-n48-k7` | 9 | 4 |
| `A-n64-k9` | 32 | 4 |
| `A-n80-k10` | 79 | 4 |

這些檔案不是 parser 誤判：路線資料實際沒有該 customer，且 SA／原版 VS
副本一致。舊 C++ 只替檔案中出現的 customer 寫入 fixed-route position；缺失
customer 的 position 保持未初始化。

歷史重播顯示舊 Windows 執行時該位置實際為 0。因此 legacy profile 做以下
處理：

1. 原始文字檔完全保留，不修改。
2. 建模時讓缺失 customer 的 `fixed_route_owner=0`。
3. 不調整 archive 保存的 fixed-route free capacities。
4. YAML 加入 `legacy_compatibility.profile: missing_fixed_route_owner_zero`，避免
   被誤認為正常資料。

這是在重現舊執行行為，不是在宣稱 customer 正確的業務歸屬就是 route 0。
若未來取得正確 Gurobi fixed-route，應建立新的修正版 problem ID／baseline，
不可覆蓋 legacy profile。

## owner=0 歷史重播證據

使用 archive 的 A-n32、11,220 transitions 歷史結果比較：

| 設定 | Seed | 結果 |
|---|---:|---|
| MaxTransfer=2 | 1 | owner 0 完整吻合；owner 1～4 皆失敗 |
| MaxTransfer=3 | 1 | owner 0 完整吻合 |
| MaxTransfer=4 | 1 | owner 0 完整吻合 |
| MaxTransfer=2 | 2 | owner 0 完整吻合 |

「完整吻合」包含 generation、objective、feasibility、transfer vehicle count、
所有 routes 與 route order、transferred customers。四份原始 SA solution 已保存於
`oracles/sa/A/`。

限制：A-n48、A-n64、A-n80 沒有 archive 歷史 solution；對它們採 owner=0 是根據
完全相同的缺欄位型態與舊配置行為所作的相容推論，仍需在跨題驗證結果中標記。

## 已完成的工具驗證

- 112 組來源 matrix 與檔名參數完整。
- 96 組 canonical YAML 與 raw source 直接一致。
- 16 組 canonical YAML 與 manifest 指定的 owner=0 相容語意一致，原 capacities
  保持不變。
- 單題、seed 1、1 transition 的 CLI smoke test：CDELS／C++ oracle exact match。
- Resume smoke test：第二次執行沒有新增或重跑已完成 task。
- 不可行結果的數值契約已固定並有回歸測試：`raw_objective` 是路線成本加
  transfer 成本，`legacy_penalty` 為不可行時固定加 100（可行時為 0），
  `legacy_search_score = raw_objective + legacy_penalty`，且正式輸出與驗證器皆
  使用 `legacy_search_score` 核對舊演算法結果。
- 驗證命令除了 CDELS／C++ oracle exact comparison，也會以 problem evaluator 獨立
  重算最終分數、feasibility 與 transfer vehicle count；結果列保留上述三種分數。

Smoke test 只證明驗證命令與續跑機制可用，不代表 96 組跨題 baseline 已完成。

## 延後項目

- 舊 config snapshot 的 `timeout_seconds` 遷移：等算法與驗證流程穩定後再處理。
- Python 流程優化、Numba 與 legacy bug 修正版：跨題 baseline 完成後才開始。
