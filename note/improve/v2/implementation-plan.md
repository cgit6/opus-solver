# OptiForge 實作前計畫

狀態：D60 已重新收斂儲存架構並修正 D44 的 checkpoint payload 入庫方案；D61–D62 已收斂 `legacy-v2`／`managed-pcg32-v1` 分流、stream topology 及第一批 primitive ABI，但均尚未實作或驗收。P0 已完成，P1 stable parameter-group loader 第一單元已存在但作為凍結候選草案，目前回到實作前方案複核，停在 solver YAML 遷移前。基準：discuss.md D27–D62；歷史討論不重寫，較晚的明確修正按其邊界使用。

## 1. 產品範圍與取捨

OptiForge 是純算法模擬的實驗控制與證據擷取層。沿用現有 solver／problem registry 與題庫載入；現有 seed 派生及 global NumPy／Numba RNG 只保留為 `legacy-v2` 相容路徑，managed 路徑使用 D61–D62 的 task root／semantic stream／PCG32 契約。新增可恢復的 task session、計時／停止控制、本機交易記錄與完整結果發布。沒有證據支持推翻整個底層；也不宣稱這些功能是其他框架沒有的研究創新。

採混合搭建：自建對本專案算法／問題適配所需的最小控制層，復用現有可驗證底層、SQLite 交易實作，分析及調參交給外部工具；不為湊框架功能再造統計／UI／調參輪子。外部工具以穩定 CLI／原始資料契約整合，這次不承諾已實作 irace／SPOT／SMAC 的全部專用 connector。

算法、problem model、參數可頻繁修改；保存結果＋當次實際設定，人工 solver_version 完全信任。沒有算法／環境可執行快照、source hash、自動版本偵測、跨執行結果重用、內建統計／排名／製圖／調參。舊 seed 接受／收集優化器維持独立入口。

一 experiment 一算法人工版本、多個固定參數組。單次凍結執行可產生內部 group key；但新 managed experiment 跨檔引用時，solver YAML 的每組參數必須有明確、唯一且跨 start 穩定的 key，禁止列表 index。最終對應在啟動前保存，續跑不靠來源重新建構。全組／全問題／全 repeat 合法完成才整場發布；跨 experiment 批量啟動各自發布。

同名 start 開新 attempt、全重跑，任何實際執行設定差異都不能 resume。新執行失敗保留上一版完整正式成果。新成果正式成功後舊版不作永久歷史；對不同算法版本有永久比較需求時用不同 experiment，或在替換前自行保存匯出包。

## 2. 架構落點（新模組名稱為此計畫候選）

| 邊界 | 目前可沿用的落點 | 新增／調整責任 |
| --- | --- | --- |
| 解析與預檢 | tools/solver_config_loader.py、engine/configs.py、engine/assembly.py | execution/plan.py：一次讀取及解析 experiment／solver／problem，建立完整 typed actual_config、組映射、輸入身份、tasks／task-root map、resolved RNG contract／stream manifest、模式相容矩陣及 plan digest；managed CLI 不提供 execution override |
| 註冊與 session | solver/registry.py、problem/interface.py、problem/registry.py | execution/session.py：可選受控 session adapter、每 task RNG registry、stable stream ownership／PCG32 adapter state、必要依賴、驗證及公共解 codec；不依賴 SQLite |
| 執行與並行 | simulator/core.py、machine/core.py、ProblemBank／SHM | execution/controller.py、budget.py、ownership.py：擁有權、狀態機、計時、停止、完整訊息、保存、恢復；基本 legacy 路徑先保留 |
| 持久化 | 目前沒有通用中途交易記錄 | persistence/store.py、schema.py、objects.py：每 experiment 一 SQLite 控制帳本，owner fence、checkpoint descriptor／完成事務、冪等操作、正式引用；checkpoint payload 統一使用外部不可變 object |
| 可讀包 | tools/show.py／stat.py 的格式可參考 | evidence/export.py、research.py：typed 原始結果＋設定＋manifest＋可選事件，ready 後正式切換；不經 legacy rmtree 寫入正式路徑 |
| CLI | cli/run、cli/exp、cli/replay | cli/simulate：明確 start／resume／status／export／publish；舊入口不刪、不重新宣稱其語意 |

資料流：解析並凍結完整計畫 → 全場能力預檢與身份／owner 驗證 → 保存計畫 → controller 派 task → session 在額度內求解與驗證 → 安全點產生獨立 payload → 外部 object durable-ready → SQLite 事務發布 descriptor／終止交易 → 完整可讀包 ready → 交易切換 official。

只有 controller／store 能寫執行權威；solver 不寫 SQL／檔案、不選 seed、不自行發布。問題相關實評估不移出額度；第一版不做跨 task 共用已評估候選快取。

## 3. 最小資料契約

### 實際設定與身份

- ExperimentIdentity：內部 UUID、合法唯一名稱、原始 canonical 管理目錄。先以同一物理目錄持久鎖取得 owner，再單例交易讀／建 UUID；鎖檔不刪除重建。
- AttemptPlan：單調 attempt 序號、人工 solver_id／solver_version、problem type／model 人工版本、完整 typed actual_config、穩定組 key→完整參數映射、控制設定、worker、初始化來源、研究／觀測設定、輸入集合、預期 task 集、實際 task-root assignment、root／stream derivation version、RNG profile／core／init-adapter／primitive-suite／solver-contract IDs、static topology／dynamic templates／resolved stream manifest digest、能力及 canonical plan digest。任一 RNG identity codec 或 contract version 改變都必須改變 plan digest。它由來源一次解析並在派工前提交；worker 不重新讀 YAML。
- TaskIdentity：experiment UUID、attempt、group_key、problem input identity、repeat index；task root／stream seed 是 assignment 不是身份。Attempt 是執行歸屬，infrastructure retry／resume 不默認將 attempt、worker、group 或排程順序混入 RNG identity；fresh resample 必須使用新的明示 sample identity。不得以相同 backend seed 跨版本去重。
- Control：max_iterations 為非 bool 正整數；max_seconds 為有限正數；至少一個，任一先到停止。checkpoint_interval_seconds 預設 60，正有限數。舊單 stop_condition 轉此格式；不把算法參數任意 int／float 強轉來判相等。
- 輸入身份：loader 規範化實際相關數值／結構（dtype／shape／順序／型別）及必要外部起點後指紋；每輸入每 attempt 保存一次，tasks 引用。resume 重載核對不同即拒絕，不靠 YAML 排版或舊解再驗證修補。
- 比較以最後真正執行的同一份 snapshot 為準，映射按 key 比較、列表按順序、值按型別及內容比較；缺失設定／不支援 codec 拒絕，不推測。只改註解或排版且最終值相同不構成差異。

### 純模擬設定分工與最小範例

現況沒有純模擬 experiment YAML；下列是 D58 決定新增的 managed 格式候選。solver YAML 繼續作算法參數唯一來源，但參數組改用穩定 key；experiment YAML 只引用 group，不複製或局部覆寫 params。具體 schema 名稱可在 P1 調整，責任分工不可暗中改變。

```yaml
# configs/solvers/bsma.yaml（節錄）
solver_id: bsma
solver_class: BSMASolver
capabilities:
  problem_types: [mkp]
  encodings: [binary]
  directions: [max]
parameter_groups:
  - key: baseline
    params:
      pop_size: 20
      z: 0.08
      ctf: tanh_abs
  - key: high_z
    params:
      pop_size: 20
      z: 0.15
      ctf: abs_pow_17
```

```yaml
# 一場純模擬 experiment；固定迭代、可進 exact 能力預檢
schema_version: 1
experiment:
  name: bsma_v3_comparison
  solver_version: "v3"       # 使用者人工維護，系統完全信任
problems:
  type: mkp
  dataset: WEISH
  ids: [weish01, weish02]
solver:
  config: configs/solvers/bsma.yaml
  groups: [baseline, high_z]
execution:
  rng_profile: legacy-v2       # 此例只示範既有 v2 assignment；不具 managed exact-checkpoint 能力
  repeat_count: 3
  worker_count: 4
  limits:
    max_iterations: 10000     # 不使用的 max_seconds 直接省略
  checkpoint_interval_seconds: 60
  seed_plan:
    mode: derived_base_seed
    base_seed: 42
    strategy_version: mkp.task-seed.v2
```

固定時間只寫 `max_seconds`；雙上限同時寫 `max_iterations` 與 `max_seconds`，任一先到即停。包含 `max_seconds` 的設定在啟動前即不具 exact fixed-work 資格，不能依某次實際 stop reason 改判。

下列人工 seed assignment 同樣是 `legacy-v2` 範例；managed task-root codec 尚待獨立定版。Tagged union 的多餘欄位即使為 null 也拒絕：

```yaml
# 同一 repeat 在所有 problems 使用相同 seed 數值
seed_plan:
  mode: explicit_repeat_seed_assignment
  scope: all_problems
  seeds: [101, 202, 303]
```

```yaml
# 每個 problem 明列每次 repeat 的 seed
seed_plan:
  mode: explicit_repeat_seed_assignment
  scope: per_problem
  seeds:
    weish01: [101, 202, 303]
    weish02: [401, 502, 603]
```

`repeat_count` 是唯一次數來源，seed lists 只驗證長度。所有 groups 預設共用展開後的 problem×repeat assignment map，但各 task 建立獨立 registry，每條 semantic stream 有單一 owner 與獨立 mutable state；這只表示 paired initialization，不認證相同隨機路徑、獨立樣本、CRN 或公平。

現有 `mkp.task-seed.v2` 整數派生及 explicit seed list 為 `legacy-v2` 相容契約。Managed 設定可保留 derived base／explicit repeat／task root 的使用者 intent，但必須依下節固定的 `OFRNGTLV` canonical codec 解析為 task root，再由 semantic HMAC 形成 StreamSeed256；小整數不得直接假裝為 StreamSeed256 或 PCG backend seed。一般 YAML 禁止 raw StreamSeed256／seed64／seq63／increment／state override；test／golden 與 checkpoint restore 另走明示入口。Codec、schema、strategy、contract 或 adapter ID 改變必須升版並改變 plan digest，不得沿用 v2 名稱或隱藏 fallback。

controller 一次讀取來源，解析及驗證後先提交 immutable AttemptPlan，才派 tasks；來源路徑只是 provenance。problem pack／SHM 對應保存的輸入身份，worker 重啟重載時依指紋核對。來源提交後改動只影響下一次 start；resume 使用 committed plan。

### Checkpoint／完成／觀測

- CheckpointObject：`external_object_v1` 不可變 payload，含 envelope／adapter codec 版本、不含秘密的 execution context、完整 solver／problem／evaluator 動態依賴、RNG registry topology version／epoch、每個 live／resume-relevant stream 的 stable key、owner、algorithm／adapter／state-schema 及完整 PCG32 `state + odd increment`、初始化階段、完成 iteration／evaluation 計數、solve_ns、已驗證 incumbent 與事件 cursor／首次達標狀態。不得只存 root／StreamSeed256 後於 resume 重播。Object digest 覆蓋實際儲存的完整 bytes，不含 digest 自身、路徑或 DB descriptor；不把相同 digest 宣告為邏輯狀態等價證明。沒有能重建後續行為的完整 adapter state 就不宣告可續跑。
- CheckpointDescriptor：SQLite 中的邏輯 checkpoint 發布事實，含 operation／checkpoint ID、owner generation、epoch，task／attempt 關聯、`storage_kind=external_object_v1`、安全相對路徑、object digest、byte size、format version、execution-context digest 與 latest 關係。Descriptor 只能引用已 durable-ready 的 object；恢復前仍需重驗 object。
- TaskOutcome：schema_version、identity／group 全參數引用、task-root／stream manifest 引用、RNG profile／contract versions／保證等級及 legacy／managed 降級原因、人工版本、kind=`solution` 或 `not_found`、公共 typed solution／objective、feasibility／驗證證據、iteration／evaluation、solve_ns、stop_reason、終止實際工作及到限證據。不得只輸出模糊的單一 `seed`。not_found 用 null 解／目標、未知可行性，不證明不可行；error 是診斷不是合法完成。
- 非有限 objective 不默認有效，problem codec 明確允許才可表達；未知／NaN 不改成 0。陣列保留 dtype／shape／值，整數不降成浮點，向量不壓成單值；用帶型別的 JSON 可讀表示，不能安全表達就拒絕，不寫 pickle 給分析者。
- Observation：task、seq、kind、產生且驗證時 solve_ns／iterations／evaluations、已驗證 objective、target_id（如適用）。非必須保存全候選解。監測模式、觸發點、採樣頻率、target 定義啟動前保存；輸出是實際觀測而非補點插值。
- Scalar target 採 problem 的明確 max／min 方向及 >=／<= 閾值；向量／多目標須有已註冊、預先宣告的比較器 ID／參數，未知就不支援 target-hitting，不猜排序。target 判斷只用已有驗證值，不額外評估或抽 RNG。
- 觀測關閉預設；啟用或更改是設定變更、新 attempt。採樣只表示首次觀測達標；完整監測相關有效解才稱實際首次。新 incumbent 交付仍遵一致政策，不能以關閉軌跡為由改變驗證或丟完整 best。

### 研究設定

ResearchSpec 為可選：stage=`exploration`／`confirmation`，用途文字可說 pilot／tuning／ablation；factors 為改動描述及預期固定條件；refs 為固定 experiment UUID／attempt／可選 task；comparison_group 為外部比較標識；splits 為具名集合及明確 input identity／repeat／seed 對應。

不隨 official 移動引用，不認證人工 stage、唯一變因、holdout 獨立性或因果；可記錄重疊證據，不能認證未記錄研究歷史。目標／預算／起點資源／problem input／人工版本／實際 seed 均可由外部工具核對，統計判讀不內建。

## 4. SQLite 與權威狀態

每 experiment 管理目錄含 experiment.sqlite、SQLite 伴隨檔、鎖、checkpoint `staging/`／`objects/` 與受保護分析包。路徑相對管理目錄；SQLite、staging 與 objects 須位於同一受支援的本機檔案系統，WAL＋synchronous FULL 為待驗證設定。不支援網路共享 WAL、跨 mount 的 checkpoint 發布、多裝置同時執行、活 DB 的普通檔案複製。

第一版表族：meta（schema／UUID／original_root／owner_generation）；attempts（plan／設定／狀態）；inputs；groups；tasks（expected identity／task-root assignment／stream-manifest reference／狀態）；checkpoints（descriptor／object reference／latest／驗證狀態）；outcomes；events；save_operations（冪等確認）；packages（ready／protected／delete_claimed 等生命週期）；official（單列 attempt／package 引用）。主鍵／外鍵涵蓋 experiment／attempt／task 歸屬，不能僅靠 backend seed／StreamSeed256 去重。Checkpoint payload 不存於 SQLite BLOB，v1 不按大小分流。

交易規則：

1. freeze 全部相關計算，在同一安全點建立與 live runtime 完全分離的 immutable payload。不是僅凍結 solver 而依賴仍改變，也不是泛稱 deepcopy 就完整。
2. payload 先在 staging 完整寫入、計算 digest、file fsync 及核對大小；再以同檔案系統的 no-clobber 原子發布進入 objects，完成 directory fsync 後才取得 durable-ready。任一步驟失敗不得建立 checkpoint descriptor。
3. durable-ready 後，checkpoint descriptor、進度／solve_ns／incumbent 摘要、尾段 events／cursor／首次達標狀態與 save ID 在同一 SQLite 事務中提交，成功後依 epoch 單調條件替換 latest；失敗不覆寫舊 committed，新 object 成為可辨識 orphan。
4. 正常 task 完成：完整合法 outcome、尾段 events／cursor／首次達標狀態及 completed 同交易。只有 committed completed 才跳過，優先於更舊 checkpoint。完成不必額外保存完整 solver 快照。
5. ACK 遺失：以同 operation ID 查詢事實／冪等重試；不得重複 task／event、倒退 latest。不能把 ACK 未收到說成必然未保存。
6. official 交易切換前，同交易重核目前 attempt／owner generation／全 task 合法 completed／package ready、受保護及歸屬。GC 已宣告刪除包不能發布；package ready 不代表有發布權。

Checkpoint object 恢復前必須重驗存在性、byte size、完整 digest、format version 與 execution-context digest。相同 digest 路徑已存在時先完整驗證才可冪等重用；不相符是完整性衝突，不得覆寫。v1 只列出 staging／orphan／missing／corrupt 診斷，不自動刪除或靜默回退至舊 checkpoint。

attempt 狀態至少 planned／running／interrupted／blocked-incompatible／compute_complete／published／failed／superseded。`blocked-incompatible` 表示資料保持完整但目前 reader／contract 不支援：禁止 fallback、resume 與求解，保存原資料及診斷，安裝相容版本後可重新驗證；不得混同資料損壞或永久 failed。單純 reader／contract 未受支援只能進 `blocked-incompatible`；`failed` 的診斷另區分資料損壞、已知 contract／context mismatch、未停止依賴及其他執行錯誤。新 start 接管較舊未完成 attempt 後，不復活它的恢復／發布資格。

同 experiment 一有效 owner／active attempt；跨進程互斥及 DB generation fencing。舊 work 未確認停止且隔離未成立時，不開始共享資源的恢復／新求解；DB fence 不能單獨阻止遠端仍在計算。狀態讀取可在舊 official 可用時進行。

停止 scope 首版選本機 Linux cgroup v2 作部署候選，不採逐 PID 清單作完整證據。新增 execution_scopes 表保存 experiment／attempt／task、owner generation、啟動 token、主機 boot identity、唯一不可重用 scope 路徑／建立身份與生命週期；建立前先提交 scope intention。launcher 啟動先阻塞，不啟動算法／評估依賴，確認被放入正確 scope、權限邊界成立且 owner 有效，才放行；launcher 的生命週期監督與放行 token 也須避免父死後晚放行。已在 scope 的 worker 才能 fork 計算依賴，不靠子程序出生後補登記；不授予其移出受管範圍的權限。

接管核對持久 scope／啟動身份，在同有效 owner 下處理整個範圍，確認子樹 populated=0、禁止舊 launcher 再放行及必要依賴停止，才允許新求解。scope 消失／身份不同／權限不足／無法排除外部工作，保持未知、拒絕執行並明確待人工處置；不是僅看 controller PID 不見。清理不重用 scope 路徑。官方提供 fork 繼承、子樹 kill 及 populated 語義，但部署權限與納管協議仍須驗證；不提供停止零延遲，daemon／GPU／remote 計算不能自動由本機 process 子樹停止證明。[Linux cgroup v2 官方文件](https://docs.kernel.org/admin-guide/cgroup-v2.html)

## 5. Session、RNG 與停止

可選 SessionAdapter 介面：capabilities(final_plan, problem_contract, dependencies)、initialize(context)、restore(envelope, context)、advance(control)、request_safe_point()、snapshot()、validated_outcome()、stop_scope()。advance 可以分塊但「完整 iteration」由 solver 定義；子步不能冒充完整 iteration。

context 提供 task identity／獨立 RNG streams／budget／既有 problem validator／完整 incumbent 交付器／觀測器。solver 管算法狀態；problem adapter 管可變依賴、公共解及驗證；controller 管執行生命週期；store 管交易。restore 入口不再 init／重播初始 seed，也不為重建消耗主 RNG。

### Managed RNG contract

`legacy-v2` 保留現行 v2 整數 seed、global NumPy／Numba RNG 及歷史 replay 語意，但不宣稱 exact checkpoint。`managed-pcg32-v1` 的每個 task 建立獨立 registry；每條 stream 只有一個 owner，semantic identity 不依 worker、process、attempt、建立／完成順序。Static topology 與 dynamic templates 在 plan 中宣告，dynamic key 只能使用穩定 evaluation／scenario／replicate identity。無 RNG 的 component 宣告 zero-stream。

每個 managed stream 由版本化 canonical task root、owner、semantic path 及 typed dynamic keys 經 domain-separated HMAC-SHA-256 得到 32-byte StreamSeed256。`pcg32-init-split127-be-v1` 固定以 bytes `0:8` big-endian 為 `seed64`，bytes `8:16` big-endian 為 `seq_word64`，`seq63=seq_word64 & ((1<<63)-1)`、`increment=(seq63<<1)|1`；bytes `16:32` 不進 backend。Core 固定為 `pcg32-xsh-rr-64-32-v1`。一般設定不能注入 raw final seed／increment／state；不同 initialization class 的 `seq63` collision 在 experiment scope fail closed。

#### Canonical TaskRoot／StreamSeed codec

Explicit task root 是非 bool 整數 `0 <= x < 2^256` 的直接 `U256BE`；不執行 HMAC。Derived root 使用 `BaseSeed256=U256BE(base_seed)` 作 key，StreamSeed 使用 TaskRoot256 作 key。`root_class` provenance 與 problem content fingerprint 都不進 stream HMAC；fingerprint 另綁 plan／task／resume，防止跨輸入恢復。

`OFRNGTLV` envelope 固定為：magic `4f46524e47544c56`、codec version `U16BE=1`、kind `U16BE`（1=derived、2=stream）、field count `U16BE`；每個 field 為 tag `U16BE`、type `U8`、length `U32BE`、payload。Types 為 `ASCII=1`、`U64=2`、`PATH=3`、`DYN=4`，top-level tags 嚴格遞增。Stable ID regex 為 case-sensitive `[A-Za-z0-9][A-Za-z0-9._-]*`。上限為 top fields 8、ID 255 bytes、PATH 1..32 個非空 segments、DYN 0..16 keys、field payload 16384 bytes、envelope 32768 bytes、depth 1。

Derived tags 固定為：1 `strategy_id`、2 `problem_seed_identity_schema_id`、3 `problem_type`、4 optional `dataset_id`、5 `problem_id`、6 `repeat_index:U64`。缺 dataset 是省略 tag 4。TaskRoot256=`HMAC-SHA-256(BaseSeed256, complete envelope)`。Stream tags 固定為：1 `rng_contract_id`、2 `owner_id`、3 semantic PATH、4 DYN；DYN 即使空也存在。PATH payload=`U16 count + repeated(U16 length + ASCII)`；DYN payload=`U16 count + repeated(U16 name length + name + U8 subtype + U16 value length + value)`，subtype 1 是八 byte U64BE，2 是 ASCII。DYN 順序由 contract template 決定。StreamSeed256=`HMAC-SHA-256(TaskRoot256, complete envelope)`。

正向 vectors 使用獨立 test-only registry：supported strategy `derived-base-hmac-sha256-v1`；supported identity schema `problem-seed-v1`；supported contract `abc-v1` 的 owner 固定為 `solver`，允許 `[search]→empty DYN`、`[ab,c]→empty DYN`、`[a,bc]→empty DYN`、`[search,candidate]→(evaluation:U64, scenario:ASCII)`。這與下方 negative-only `empty-v1` registry 分開，兩者都不是 production contract map。

正向 golden keys：`Z32=00`×32；`K1=00`×31+`01`；`KSEQ=000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f`。Explicit anchors 為 `0→00`×32、`1→00`×31+`01`、`2^256-1→ff`×32，沒有 TLV 或 digest。其餘 vectors 固定如下；production encoder 不得替自己產生 expected：

- D0：key `Z32`；derived strategy `derived-base-hmac-sha256-v1`、identity schema `problem-seed-v1`、type `mkp`、dataset absent、problem `p0`、repeat 0；length 104；preimage `4f46524e47544c560001000100050001010000001b646572697665642d626173652d686d61632d7368613235362d76310002010000000f70726f626c656d2d736565642d7631000301000000036d6b70000501000000027030000602000000080000000000000000`；digest `ed519cd704bfcf2ab0e07a5428aac8850eeba7d2db47bd65d82cad6e9fff7ac1`。
- D1：key `K1`；同 strategy／schema／type、dataset `orlib`、problem `p1`、repeat `0x0102030405060708`；length 116；preimage `4f46524e47544c560001000100060001010000001b646572697665642d626173652d686d61632d7368613235362d76310002010000000f70726f626c656d2d736565642d7631000301000000036d6b70000401000000056f726c6962000501000000027031000602000000080102030405060708`；digest `97b743e1159b05a8111fbfe0251be2ef5941989fee87ad8dc2dd6919fb1f0191`。
- S0：key `K1`；contract `abc-v1`、owner `solver`、path `[search]`、empty DYN；length 66；preimage `4f46524e47544c56000100020004000101000000066162632d763100020100000006736f6c7665720003030000000a00010006736561726368000404000000020000`；digest `968ba887391f14a0cae0b4b941521dcd4d85ebbb9beeef2f68b8e0477c8302b1`。
- S1a：key `K1`；path `[ab,c]`；length 65；preimage `4f46524e47544c56000100020004000101000000066162632d763100020100000006736f6c76657200030300000009000200026162000163000404000000020000`；digest `9636c14739b483baade4617e2bda5b9e8687ef43860bd8ae805a26fdf44f9a2c`。
- S1b：key `K1`；path `[a,bc]`；length 65；preimage `4f46524e47544c56000100020004000101000000066162632d763100020100000006736f6c76657200030300000009000200016100026263000404000000020000`；digest `ce0266a854f0a8064beccb262e1a02733d014e35cb6f2a4f193c4af198dd4fa8`。
- S2：key `K1`；path `[search,candidate]`；DYN `evaluation:U64=0x0102030405060708, scenario:ASCII=base`；length 117；preimage `4f46524e47544c56000100020004000101000000066162632d763100020100000006736f6c7665720003030000001500020006736561726368000963616e6469646174650004040000002a0002000a6576616c756174696f6e010008010203040506070800087363656e6172696f02000462617365`；digest `ddcae87720460dcd167ad255a51236aac3af1515e44c014c2c97ef5e65403492`。
- S3：key `KSEQ`；message 與 S0 完全相同；length 66；digest `242f5186c45226761dc8eb52455c09bed6a7bc39a30104a47ca8168c7b521f7d`。Explicit／derived provenance 使用同一 root bytes 時必須得到同一結果。
- E2E：先以 D1 得到的 TaskRoot256 作 key，再使用 S0 message；length 66；digest `fd2034a0b1cb0e467a16ad605d33c56a684fe24dabb926850ac52a8a8d9a7d96`。

非法輸入以不可分割 `(outcome=REJECTED, stage, code)` 回報。`FRAMING` codes：`LIMIT_EXCEEDED`、`MALFORMED_ENVELOPE`、`UNSUPPORTED_CODEC`；`CANONICAL` codes：`LIMIT_EXCEEDED`、`SCHEMA_VIOLATION`、`INVALID_VALUE`；`SEMANTIC` codes：`UNSUPPORTED_ID`、`CONTRACT_MISMATCH`。人類訊息、exception class、offset 與 stack trace 不屬 ABI。檢查順序固定為 header／magic與外層 caps → 每 field outer length／cap／remaining bytes → nested count caps 與結構 → canonical ID → supported ID → supported contract match。所有 rejection 均在 HMAC 前，且 HMAC/RNG/registry 無副作用。合法輸入後的 provider 故障另為 `ERROR/DERIVATION_OPERATION/HMAC_PROVIDER_FAILURE`，不是 codec rejection。

Negative goldens 使用 test-only `supported_contracts={empty-v1: owner=solver, path=[search], dynamic_keys=[]}`；`ghost-v1` 只是不在 supported set 的 sentinel。每筆 expected digest absent、HMAC calls 0、RNG factory calls 0：

- G-N1 length 86，`FRAMING/LIMIT_EXCEEDED`（field count 9>8）：`4f46524e47544c56000100020009000101000000016100020100000001610003010000000161000401000000016100050100000001610006010000000161000701000000016100080100000001610009010000000161`。
- G-N2 length 50，`FRAMING/MALFORMED_ENVELOPE`（top payload 截斷）：`4f46524e47544c5600010002000400010100000008656d7074792d763100020100000006736f6c7665720003030000000a00`。
- G-N3 length 68，`FRAMING/UNSUPPORTED_CODEC`（version 2）：`4f46524e47544c5600020002000400010100000008656d7074792d763100020100000006736f6c7665720003030000000a00010006736561726368000404000000020000`。
- G-N4 length 68，`CANONICAL/SCHEMA_VIOLATION`（tags 2,1,3,4）：`4f46524e47544c5600010002000400020100000006736f6c76657200010100000008656d7074792d76310003030000000a00010006736561726368000404000000020000`。
- G-N5 length 66，`CANONICAL/INVALID_VALUE`（ID `bad/id`）：`4f46524e47544c56000100020004000101000000066261642f696400020100000006736f6c7665720003030000000a00010006736561726368000404000000020000`。
- G-N6 length 68，`SEMANTIC/UNSUPPORTED_ID`（`ghost-v1`）：`4f46524e47544c560001000200040001010000000867686f73742d763100020100000006736f6c7665720003030000000a00010006736561726368000404000000020000`。
- G-N7 length 91，`SEMANTIC/CONTRACT_MISMATCH`（`empty-v1` 卻帶 `evaluation:U64=0`）：`4f46524e47544c5600010002000400010100000008656d7074792d763100020100000006736f6c7665720003030000000a00010006736561726368000404000000190001000a6576616c756174696f6e0100080000000000000000`。

Raw decoder 與 typed encoder 分開驗收；bool、negative、oversize 只屬 typed source validation。Golden 固定跨語言 ABI；完整拒絕排列放 unit tests，截斷／length／count／bounded allocation 放 fuzz/security tests。各 CLI／checkpoint／library 入口只對其實際支援的 typed-encode 或 raw-decode 路徑映射相同 machine tuple 並驗證無副作用；不得為了測試新增 raw TLV 公開入口。不支援 codec／ID 時禁止 fallback／resume，attempt 進 `blocked-incompatible` 並保留資料，待相容環境後重驗。

Primitive suite 固定列出 `next_u32_v1`、`uniform_f64_53_v1`、strict Bernoulli、finite raw-threshold compare、`bounded_u32_v1`、descending in-place shuffle、ordered-pair-excluding、linear float64 categorical weights及 half-open affine uniform。每個 primitive 的驗證時機、draw consumption、浮點運算順序、checkpoint 不可分割邊界及 Python／JIT golden vectors皆為 ABI；未知版本拒絕。Solver stream namespace採 `solver-contract/<rng_contract_id>/<feature>`，只有明示同 contract 且通過 draw-order／vector conformance 的實作可配對初始化，仍不得宣稱 CRN。

Checkpoint barrier freeze registry 後，只保存 live／resume-relevant streams 的 stable key、owner、完整 `state + increment` 及 topology／contract versions。Restore 不 draw、不重新 init、不重跑 PCG warm-up；缺失、額外、owner mismatch、偶數 increment或未知版本都 fail closed。Closed 是不可逆 terminal 狀態；closed ephemeral stream不保存 mutable state，但 checkpoint／restore 必須保留完整 semantic identity與owner tombstone，恢復後同一 identity不得重新 materialize、重新初始化或再次 draw。

Legacy v2 派生保留 base seed＋type＋dataset＋problem＋repeat，不加入 worker／attempt／group／算法版本。組間配對相同邏輯 seed，但各自 RNG 物件不共用。啟動前保存 seed map／策略版本；派生不同邏輯位置碰撞拒絕，不偷偷換 seed。explicit seed list 重複可信任，但不宣稱獨立樣本。這段不得被解讀成 managed backend seed 或 stream derivation。

排程重現能力分開註冊及驗收：`fresh_run_schedule_independent` 只涵蓋全新固定邏輯工作；`resume_schedule_independent` 另要求所有 RNG、solver／problem 動態狀態可完整保存還原。任一含 max_seconds、牆鐘或非確定外部到達順序的終止設定，都不具 exact fixed-work 資格，即使某次恰好先達迭代上限。exact 比較涵蓋 typed outcome、驗證、計數、確定性停止原因、事件邏輯座標與 RNG／checkpoint 邏輯狀態；不比較 runtime、solve_ns、牆鐘、訊息到達順序或 PID。浮點位元等價限已驗證的相同裝置／數值環境。

不承諾物理 exactly-once。狀態不明先以 operation ID 查 store；確認未提交且舊 scope 已停止後可用新 generation 重算，但同時至多一個有效 scope、只接受一份權威 outcome，並保存重派原因、拒絕舊世代晚寫。

Managed 路徑必須把所有正式 call site 改走顯式 PCG32 state，移除 module-global NumPy／Numba draws、隱藏 Generator bridge及其他未登記來源；不得以 global RNG snapshot 假裝 managed registry 完整。Legacy compatibility 可保留 global state adapter 作明確降級能力，但不算 managed resume。已知 `config.get(run_seed, rng.integers(...))` 的 eager default 額外抽樣問題列入 regression；若改動現有路徑，不能未告知就聲稱與舊版本同軌跡，人工版本由使用者更改。

初期先用確定性測試 session 證明 controller，再遷移一個 Python solver；Numba 完整單迴圈需另作可保存顯式狀態／可停止分塊適配，未驗收前只有已確認 basic 模式，不冒稱支持 resume／hard time。這不是放棄 NumPy／Numba 或長 task 內續跑需求。

計時：每 task 單一 monotonic ns、求解／初始化／實評估區段聯集；平行執行緒不 CPU 時數加總，巢狀評估不重複扣。全部真計算靜止的純保存／載入／傳輸才暂停；cache 重建若做評估則扣。checkpoint 20 分鐘、丟失 10 分鐘，resume 還有 40 分鐘；中斷停機與失落區段不扣，不能用此聲稱總實際用時 <=60 分鐘。

deadline 是求解額度截止，不等正在進行的步驟／評估完成。不把停止等待或忽略晚結果當停止計算。能力預檢涵蓋 solver＋problem＋依賴＋完整設定；未知／不可控制組合整場拒絕，不默降 soft deadline。初始化也受停止控制。

**不能把有限測試或 process termination 宣稱成所有硬體排程下物理零延遲停止保證。**實作必須設截止前有界停止策略／停止範圍、記錄真工作停止證據；若越界便失效／error，不把越界改稱合法完成、不擅加使用者未接受的額度寬限。無法建立所需邊界的組合不啟用此模式。正常到限且完成證據已提交不再 resume 舊 checkpoint 重跑；崩潰前完成證據未提交則從 checkpoint 回滾。機制選型與可驗證範圍在停止專用驗收階段明確列出，不承諾現在已支持。

時間比較：正式比較用驗證過的隔離資源，或串行排除同研究互相競爭；不靠文字宣告就證公平，不保證排除整台機器所有外部負載。平行吞吐模式可保留，結論不能直接冒稱算法純搜尋品質。時間／時間＋迭代不保證精確重播，寫說明文件，不添加此標籤到每列結果。

新完整已驗證 incumbent 在正式時間比較中先完整不可變交付並 ACK 再推進；控制訊息含 task／owner generation／seq／驗證證據，半截不收。截止只使用完整已交付 best 或有效 checkpoint best，不截止後免費重評估。不能保證 worker 私有最後 best 零遺失。

## 6. 可讀結果、發布、讀取與清理

初版共同物理輸出域固定為專案 `output`；受管 namespace 為 `output/.optiforge-workbench/experiments/NAME`，固定結構鎖為 `output/.optiforge-structure.lock`。域根、鎖與 namespace 為保留範圍；受管根及 experiment 保存持久 marker。不存在全域 experiment 索引。所有受支援 writer（含 legacy exp／replay／show、受管建立、匯出目的地準備及 GC）在同一結構鎖內核對目標身份／受管重疊並完成對應結構變更，求解不持鎖。legacy 不得刪写受管範圍，亦不得刪除包含受管下級的祖先。

custom／nested output_root 與匯出目的地須可歸入同一既定 domain，不動態另建互相嵌套的協調域；初版破壞性寫路由拒絕 symlink，沿已確認物理路由操作。這明確收窄任意／別名寫路徑支援，不撤回 canonical 身份讀取，亦不聲稱能抵禦不合作程序任意替換祖先目錄。受控 mkdir／rename／delete 共用結構鎖；發現 domain 身份異常拒絕，不能說必然偵測所有外部競態。拒絕在建立 attempt 或求解前，不改 actual_config／checkpoint／official，不自動換路、搬移或開新 attempt。非重疊合法預設舊路徑保留；用戶處理路徑後仍按正常 start／resume 設定規則。

必需包為 manifest.json＋settings.json＋results.json；啟用軌跡時另 observations.json。JSON 使用穩定 schema／typed codec、完整 task 分母；CSV 為可選衍生品，明確要求的額外格式才加入 mandatory ready 條件。

manifest：schema_version、experiment／attempt 身份、來源 selector、匯出當下發布狀態及 official identity、組映射／預期 task 集、檔案清單與完整性證據。第一次 prepared 包可表達 prepared 狀態；發布後不就地改不可變包冒充最新時間狀態。official 匯出建立新的快照 manifest，DB publication receipt 為正式事實。

新包寫在獨立 attempt 工件目錄，驗證完整、耐久準備後 protected ready；這不是直接覆寫固定正式檔案集合。實作階段先定義檔案／目錄耐久提交步驟並 fault-test，不能只 close 檔案就聲稱斷電安全。DB 原子發布只切引用，消費者沿 official 引用解析。

必需匯出失敗保留上一版 formal 包／設定；新 compute_complete 保存，可 publish 重試不求解。發布成功後僅清理已 superseded／abandoned 且無 official／active reader／resume／protected 引用的工件；同 owner 下先 claim_delete，禁止再發布，再刪。啟動復原遇不確定包保留，不猜刪；有占用讀者時延後 GC。這是最小暫時重疊，不承諾永久歷史。

移動整目錄前停止執行／清理／讀者並乾淨關閉；普通複製到不同 canonical_root 預設唯讀，執行須新 experiment identity 全重跑，不繼承 active checkpoint。這不是安全抗竄改／全域副本偵測／跨硬體恢復承諾。

## 7. CLI 固定候選

入口 `python -m mkp.cli.simulate`：

- `plan --config FILE`：唯讀解析並輸出完整 resolved groups、problem／seed map、task matrix、limits 及 canonical digest；不建立 experiment、attempt 或 DB。預覽不是已執行證據。
- `start --config FILE [--expect-plan-digest DIGEST]`：重新解析完整 experiment execution 設定，digest 不符即在建 attempt／求解前拒絕；明確開新 attempt。若有效舊執行仍活動，拒絕，不自動殺掉。參數組按來源中的 stable key 解析並保存。
- `resume --experiment-name NAME --attempt N [--config FILE]`：使用原保存計畫；若另給 FILE，最後實際配置不同即拒絕，不自動 start。無 worker／seed／參數等恢復覆寫例外。
- `status --experiment-name NAME`：列 official、當前 attempt、合法完成／未完成／錯誤／checkpoint、owner／恢復／發布資格，不執行算法。
- `export --experiment-name NAME (--official | --attempt N) --destination DIR`：完整已提交成果可讀包；未完成內容須明確診斷模式，不能輸出為正式完整結果。DIR 須符合第 6 節同域寫入規則，已存在不得自動破壞其他成果；需要移往外部分析裝置可自行複製完整可讀包。
- `publish --experiment-name NAME --attempt N`：只重試 compute_complete 的必需包與正式切換；published 重試冪等、不求解。失去當前發布資格拒絕。

start 的成功退出代表完整正式發布；求解完成但 mandatory output fail 非成功，回報可 publish 重試。resume／publish 亦按其真正操作結果回報，status／export 成功不代表開始或完成新求解。訊號中斷保持 committed 事實、確認停止／資格診斷，不憑 Ctrl-C 成功就冒稱 checkpoint 已保存。

managed CLI 不接受 worker、seed、limits 或算法 params 的臨時 override；`--expect-plan-digest` 只核對來源解析結果，不能修改 plan。執行後權威是 committed AttemptPlan／結果包，不是原 YAML 或先前 preview。

舊 cli.run 保留基本語意及相容性測試；新控制功能走新入口，避免對舊 oneshot 無聲添加 resume 保證。舊 cli.exp／cli.replay 保留；replay 是基於 accepted seeds 新跑，不是 checkpoint。舊結果只讀／匯出，不能造假成支持恢復的新 attempts。

## 8. 分段實作與驗證 gate

以下是下一次獲得實作授權後的順序，每段小修改、針對測試、檢查證據、回報再進下一段；不一口氣改完整系統。

| 段 | 工作單元 | 必須看過的驗證證據 |
| --- | --- | --- |
| P0 | 建可重現測試環境，先不改程式；記錄 baseline | 安裝授權範圍明確後依 pyproject 建環境；既有 RNG／batch／registry／CLI／solver tests 加全套 baseline，失敗與環境原因分開；不得以目前 pytest 缺失宣稱已通過 |
| P1 | 純設定／身份／task-root matrix／codec schema | solver stable group key唯一／重排不改引用、managed index拒絕／legacy保留、無partial param override、plan唯讀且digest穩定／expect mismatch無副作用；legacy／managed schema嚴格分流，seed tagged union inactive欄位含null拒絕、all_problems／per_problem長度與覆蓋；base／explicit intent正規化成resolved root manifest，OFRNGTLV 全部正向／負向 goldens、HMAC identity codec、StreamSeed256及PCG32 slicing跨語言vectors，raw decoder與typed encoder分流；各實際 typed／raw 入口的拒絕 tuple、檢查順序、HMAC／RNG／registry零副作用及`blocked-incompatible`生命週期，不為測試新增 raw TLV 公開入口；禁止raw final override；group重排、worker、attempt不改root／stream identity，semantic key collision／owner重複／未知版本拒絕，任一RNG contract變更會改plan digest；typed objective／null／vector精度、input改值vs改排版 |
| P2 | 每 experiment store＋owner | 双process首建UUID／互斥／fence晚寫；scope intention／建立／blocked launcher／納管／放行各窗口崩潰，父死子活與 late release、禁止 scope 重用／遷出、無法確認停止拒絕；SQLite write/commit前後故障、ACK失落、operation冪等、latest不倒退、跨task歸属／completed原子優先；checkpoint staging短寫／fsync失敗／no-clobber衝突／directory fsync／object ready後DB失敗／digest損壞、orphan只報告，未完全保存不算checkpoint或完成 |
| P3 | 測試 session＋controller 固定工作恢復 | 修正 selected-task 重複 append 與 eager default draw；測試session使用真正的每-task registry，交錯tasks不互相污染；freeze期間topology／state不可變，restore不draw／init／補建stream，所有live stream逐一round trip，missing／extra／owner mismatch／unknown version fail closed；fresh-run 比較 worker=1／多worker、反序／子集的完整邏輯觀測；resume 比較 A uninterrupted、A checkpoint→同worker跑B→恢復A、fresh worker恢復A，恢復前重驗object size／digest／format／context，逐步核候選／事件／primitive trace／RNG final state／problem依賴／進度／budget；lost段state/time/events一起回滾 |
| P4 | 一個 Python solver／problem 適配 | 完整盤點選定solver每個RNG call site並映射approved primitive，不再呼叫module-global `np.random`、`default_rng`或hidden seed bridge；遷移前後reference路徑＋手動版本責任，明示初始化／主迴圈phase差異，不把legacy軌跡差異誤報bit-identical；eager default regression；不同安全點interrupt/restore逐步核primitive call、branch、candidate、evaluation、event及state，同時確認真实validator计费、notfound不是error、動態problem依賴與所有全域RNG隔離；不得只比最後最佳值 |
| P5 | 停止範圍與模式能力 | initialize／longadvance／eval／子process／取消失敗測試；实計算停止證據、晚寫fence、正常limit不復活checkpoint、違約error不發布；同一測試 session 的完整觀測對照加入可控 ACK 延遲、半截 IPC、亂序／重送與截止交錯，核對第一 incumbent／首次驗證、等待時全部 solve／eval 靜止、只接完整有效訊息、終止後／失效世代不晚寫、不補私有 best；交付 gate 未過不能放行正式時間比較。未知support全場預檢拒絕；不得把有限測試當普遍物理零延遲保證 |
| P6 | 完整包、official切換與reader／GC | mandatory包寫一半／耐久前故障／DB切換前後／old资格重試／newstart接管／GC竞态／active reader；checkpoint objects、DB snapshot與受保護分析包的完整目錄關閉後搬移，不把活SQLite主檔普通複製當備份；managed建立 vs legacy reset 雙進程檢查／刪除競態、所有 writer 同域鎖、祖先包含受管資料與 symlink／域身份異常拒絕、鎖 inode 不刪換；全部失败旧formal不變、complete可只重export、每task分母與schema精度、manifest不是最大序号猜official |
| P7 | 研究／觀測介面與CLI | 多targets comparator/完整監測vs採样座標；events+cursor與checkpoint／completion同txn且冪等；人工split不認證公平；start/resume/export/publish明確資格及退出狀態；旧exp/replay/run regressions |
| P8 | NumPy／Numba 進階適配與文檔 | managed Python／Numba共用顯式 `managed-pcg32-v1` state及同一primitive vectors；legacy global NumPy／Numba internal RNG只作明確降級能力，不算managed resume；從next_u32到所有高階API核raw output、bounded rejection、shuffle／pair trace、categorical／affine float bits、異常zero-draw及final state，JIT禁止改變RNG計算的fastmath／FMA；所有正式solver完成call-site coverage，未遷移者關閉managed capability；Numba顯式狀態／分塊停止完整性逐一證明，fresh／resume能力分開；fixed logical work同裝置對照、任何含時間上限模式不exact、60sec請求非保證、真實端到端效率不等solve budget；全套regression通過或逐項明示差異 |

每个里程碑有独立可停状态；可先交付可靠固定迭代＋内部恢复路径，但整个用户范围仍包括时间、组合上限与Numba适配，不能把阶段完成冒充项目全部完成。任何测例发现隐含状态或不可控依赖，回到适配边界，不通过偷减契约来使测试绿。

## 9. 本次稽核与实施边界

已读程式：engine/models.py、configs.py、assembly.py；simulator/core.py、machine/core.py；solver／problem registry/interface；rng/context.py、factory.py、strategy.py、seeding.py；CLI run/exp/replay；tools/show.py、stat.py、solver_config_loader.py，相关RNG／batch测试片段。算法本体仅选读／搜尋片段，不算所有solver状态的完整审计。

P0 已以 Python 3.12.3 建立忽略版控的 `.venv`，依 `requirements.txt` 安裝固定執行依賴，另明確安裝 pytest 8.3.5；`pip check` 通過，pytest 收集 344 項無錯。RNG／batch／registry／CLI／solver 針對性 baseline 為 144 passed in 51.45s，完整 baseline 為 344 passed in 27.13s。這只證明修改前既有測試基線，不證明尚未實作的執行恢復、取消、交易或發布契約。

P1 第一單元已新增 solver `parameter_groups` schema 與 stable key lookup；新舊參數 schema 不得並存，group key 必須非空、去除首尾空白且場內唯一，managed lookup 拒絕 legacy `params`。legacy index loader 與既有 YAML 維持相容。loader 測試 21 passed、legacy／CLI 針對性回歸 71 passed、完整回歸 351 passed；現有 solver YAML 尚未遷移，未自動產生跨 start key。

獨立質詢／工程／實驗設計攻防已完成 D53；工程及實驗設計各自完整核對 D27–D53，均判定 PASS-with-runtime-gates。最終 root 查漏另形成 D54 新舊輸出共存保護，D55 文件 gate 通過。其後 D56–D58 補齊 repeat seed、併發重現能力與設定分工，D59 通過相關一致性複核。D60 將 D44 的 checkpoint payload 入 SQLite 修正為 SQLite descriptor 加外部不可變 object；D61–D62 再將現行 RNG 收縮為 legacy compatibility，新增尚未實作的 managed PCG32 registry、stream topology及primitive ABI。因此早先文件 gate 不能直接當成當前方案已全部收斂。這些文件結論不是功能驗收；P0 只建立修改前測試基線，P1 候選變更保留但凍結，須待後續方案完成再重做實作 gate。

SQLite事实依据：[atomic commit](https://www.sqlite.org/atomiccommit.html)、[isolation](https://www.sqlite.org/isolation.html)、[appropriate uses](https://www.sqlite.org/whentouse.html)、[limits](https://www.sqlite.org/limits.html)、[internal versus external BLOBs](https://www.sqlite.org/intern-v-extern-blob.html)、[WAL](https://www.sqlite.org/wal.html)、[WAL-mode file format](https://www.sqlite.org/walformat.html)、[Backup API](https://www.sqlite.org/backup.html)與[synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous)。原子／耐久成立受儲存、OS／檔案系統契約與正確配置前提約束，不承諾任意裝置斷電均安全；BLOB 測試數字不當通用架構閾值。

### 需求覆蓋索引

| 討論決策 | 本計畫落點 | 實作驗證 gate |
| --- | --- | --- |
| D01–D05 重現性及三種停止模式 | §3 Control、§5 RNG／OR 截止與時間模式邊界 | P1、P3、P5、P8 |
| D06–D11 成果保護、problem／repeat／task 內續跑 | §4 交易與狀態、§5 session、§6 完整發布 | P2–P6 |
| D21–D24 結果＋設定、人工版本信任、無可執行快照 | §1、§3 actual_config／人工版本 | P1、P7、文檔 |
| D25–D27 保存匯出與研究證據、分析外置 | §1、§3 Research／Observation、§6 | P1、P7 |
| D28–D31 experiment／整組發布與固定組映射 | §1、§3 身份／計畫、§4 official | P1、P2、P6 |
| D32–D35 全設定差異新跑、原執行續跑、無自動重用 | §1、§3 snapshot、§7 start／resume | P1、P3、P7 |
| D36–D39 完整安全點、時間回滾、初始化／評估計時 | §3 Checkpoint、§4、§5 budget | P2–P5 |
| D40–D42 真停止、終止證據與組合能力預檢 | §2 資料流、§4 scope、§5 deadline | P2、P5、P8 |
| D43–D47 同步 SQLite、先包就緒、owner／身份／接管 | §3–§4、§6、§7 | P2、P3、P6、P7 |
| D48–D50 RNG 適配、驗證交付、時間軸、input 與完整分母 | §3、§5 | P1、P3–P5、P8 |
| D51–D52 CLI／來源、研究宣告與事件共同提交 | §3–§4、§6–§7 | P1、P2、P7 |
| D53–D54 出生納管、交付對照、新舊 writer 保護 | §4 scope、§6 結構鎖、§8 | P2、P5–P7 |
| D56–D58 seed assignment、併發重現能力與設定分工 | §3 設定範例、§5 RNG／能力、§7 CLI | P1、P3–P5、P7–P8 |
| D60 SQLite 控制帳本＋外部不可變 checkpoint object | §2 持久化、§3 CheckpointObject／Descriptor、§4 發布交易、§6 完整管理目錄 | P2、P3、P6 |
| D61–D62 managed RNG task root／semantic streams／PCG32 adapter／primitive suite／checkpoint state | §2 plan／session、§3 AttemptPlan／CheckpointObject／TaskOutcome、§5 Managed RNG contract | P1、P3、P4、P8 |

D12–D20 的價值／定位演化保留在 discuss.md；已被 D21 等明確撤回的快照需求不重新加入。此索引是設計覆蓋，不是執行測試完成清單。
