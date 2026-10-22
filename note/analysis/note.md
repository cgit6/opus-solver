# 分析模組

## 概述

模擬過程中會產出每一次獨立執行 n 次迭代的最佳解，還有評估時間以及 "評估物品" 的時間。例如，預計獨立迭代 20 次，那就會有 20 筆算法執行結果的資料(最佳解、最佳適用值、算法執行時間、物品評估時間)

## 系統重構討論文件

以上保留原始分析模組筆記。系統重構的責任分工、題目設定、算法狀態、評估、完整歷史交付與後續工作，另整理於：

- [文件索引與分類](system_redesign/README.md)
- [設計決策紀錄](system_redesign/design_decisions.md)
- [Python 如何呼叫 C++ 與失敗 task 的單獨重跑](system_redesign/14_python_cpp_invocation_and_failure_replay.md)
- [task 異常紀錄、不中斷實驗與結果保存](system_redesign/15_task_failures_and_result_storage.md)
- [待議清單](system_redesign/13_open_questions.md)

整理日期：2026-10-21。這是文件整理，不表示已修改系統或完成新架構驗證。
