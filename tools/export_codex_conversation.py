"""Export the visible user/assistant messages from one Codex session branch.

Codex can split a long conversation across paginated JSONL files and can fork a
new branch from an earlier ordinal.  The ``history_base`` metadata is therefore
followed recursively; simply concatenating files with the same session id would
also include messages from abandoned branches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@dataclass(frozen=True)
class Message:
    ordinal: int
    timestamp: str
    role: str
    message_id: str
    text: str
    block_count: int


def _own_thread_id(path: Path) -> str:
    ids = UUID_RE.findall(path.name)
    if not ids:
        raise ValueError(f"Cannot infer thread id from {path}")
    return ids[-1]


def _build_thread_index(roots: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root in roots:
        for path in root.rglob("*.jsonl"):
            thread_id = _own_thread_id(path)
            previous = index.get(thread_id)
            if previous is not None and previous != path:
                raise ValueError(
                    f"Duplicate thread id {thread_id}: {previous} and {path}"
                )
            index[thread_id] = path
    return index


def _read_prefix(path: Path, byte_limit: int | None) -> bytes:
    with path.open("rb") as stream:
        data = stream.read() if byte_limit is None else stream.read(byte_limit)
    if data and not data.endswith(b"\n"):
        raise ValueError(f"Byte limit does not end at a JSONL boundary: {path}")
    return data


def _records(data: bytes, path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.splitlines(), start=1):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return result


def _walk_history(
    path: Path,
    index: dict[str, Path],
    byte_limit: int | None,
    active_snapshot_size: int,
    seen: set[tuple[Path, int | None]],
) -> tuple[list[dict[str, Any]], list[tuple[Path, int]]]:
    effective_limit = active_snapshot_size if byte_limit is None else byte_limit
    key = (path, effective_limit)
    if key in seen:
        raise ValueError(f"Cycle in history chain at {path}")
    seen.add(key)

    data = _read_prefix(path, effective_limit)
    records = _records(data, path)
    if not records or records[0].get("type") != "session_meta":
        raise ValueError(f"Missing session_meta at start of {path}")

    history = records[0].get("payload", {}).get("history_base")
    inherited: list[dict[str, Any]] = []
    sources: list[tuple[Path, int]] = []
    if history:
        parent_id = history["thread_id"]
        parent = index.get(parent_id)
        if parent is None:
            raise ValueError(f"Cannot find history thread {parent_id}")
        inherited, sources = _walk_history(
            parent,
            index,
            int(history["end_byte_offset"]),
            active_snapshot_size,
            seen,
        )
        expected_end = int(history["end_ordinal_exclusive"])
        parent_ordinals = [
            record["ordinal"]
            for record in inherited
            if isinstance(record.get("ordinal"), int)
        ]
        if parent_ordinals and max(parent_ordinals) >= expected_end:
            raise ValueError(
                f"History cutoff mismatch for {parent}: "
                f"max ordinal {max(parent_ordinals)} >= {expected_end}"
            )

    return inherited + records, sources + [(path, effective_limit)]


def _message_text(content: Any) -> tuple[str, int]:
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False, sort_keys=True), 1

    pieces: list[str] = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            pieces.append(block["text"])
        else:
            pieces.append(json.dumps(block, ensure_ascii=False, sort_keys=True))
    return "".join(pieces), len(content)


def _extract_messages(records: list[dict[str, Any]]) -> list[Message]:
    messages: list[Message] = []
    for record in records:
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload", {})
        if payload.get("type") != "message" or payload.get("role") not in {
            "user",
            "assistant",
        }:
            continue
        text, block_count = _message_text(payload.get("content", []))
        messages.append(
            Message(
                ordinal=int(record["ordinal"]),
                timestamp=str(record.get("timestamp", "")),
                role=str(payload["role"]),
                message_id=str(payload.get("id", "")),
                text=text,
                block_count=block_count,
            )
        )

    ordinals = [message.ordinal for message in messages]
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise ValueError("Visible message ordinals are duplicated or out of order")
    return messages


def _canonical_digest(messages: list[Message]) -> str:
    digest = hashlib.sha256()
    for message in messages:
        value = {
            "block_count": message.block_count,
            "message_id": message.message_id,
            "ordinal": message.ordinal,
            "role": message.role,
            "text": message.text,
            "timestamp": message.timestamp,
        }
        digest.update(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _fence(messages: list[Message]) -> str:
    longest = 0
    for message in messages:
        for run in re.findall(r"~+", message.text):
            longest = max(longest, len(run))
    return "~" * max(8, longest + 3)


def _render(
    messages: list[Message],
    sources: list[tuple[Path, int]],
    active: Path,
) -> str:
    digest = _canonical_digest(messages)
    users = sum(message.role == "user" for message in messages)
    assistants = sum(message.role == "assistant" for message in messages)
    fence = _fence(messages)
    generated_at = datetime.now(timezone.utc).isoformat()

    lines = [
        "# Codex 完整對話逐字稿",
        "",
        "> 本文件從 Codex 原始 JSONL session 記錄重建目前這條對話分支。",
        "> 保留所有 `user` 與 `assistant` message 的原文、時間、ordinal 與 message id；",
        "> 包含 IDE context、response annotations、環境訊息等原始記錄。",
        "> system/developer 指令、工具呼叫與輸出、內部推理不屬於雙方可見對話，未納入逐字稿。",
        "",
        "## 完整性資訊",
        "",
        f"- 匯出時間（UTC）：`{generated_at}`",
        f"- Active session：`{active}`",
        f"- 對話訊息總數：`{len(messages)}`",
        f"- User 訊息：`{users}`",
        f"- Assistant 訊息：`{assistants}`",
        f"- 第一筆 ordinal：`{messages[0].ordinal if messages else 'N/A'}`",
        f"- 最後一筆 ordinal：`{messages[-1].ordinal if messages else 'N/A'}`",
        f"- Canonical message SHA-256：`{digest}`",
        f"- Session 分頁／fork 來源數：`{len(sources)}`",
        "",
        "### Session 來源鏈（由最舊到最新）",
        "",
    ]
    for path, byte_limit in sources:
        lines.append(f"- `{path}`（讀取前 `{byte_limit}` bytes）")

    lines.extend(["", "## 對話內容", ""])
    for number, message in enumerate(messages, start=1):
        lines.extend(
            [
                f"### 訊息 {number:04d}｜{message.role}",
                "",
                f"- Timestamp：`{message.timestamp}`",
                f"- Ordinal：`{message.ordinal}`",
                f"- Message ID：`{message.message_id}`",
                f"- Content blocks：`{message.block_count}`",
                f"- 原文字元數：`{len(message.text)}`",
                "",
                f"{fence}text",
                message.text,
                fence,
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--session-root",
        type=Path,
        action="append",
        required=True,
        help="May be supplied more than once.",
    )
    args = parser.parse_args()

    active = args.active_session.resolve()
    active_snapshot_size = active.stat().st_size
    index = _build_thread_index(args.session_root)
    records, sources = _walk_history(
        active,
        index,
        None,
        active_snapshot_size,
        set(),
    )
    messages = _extract_messages(records)
    output = _render(messages, sources, active)
    args.output.write_text(output, encoding="utf-8")

    print(
        json.dumps(
            {
                "active_snapshot_bytes": active_snapshot_size,
                "assistant_messages": sum(m.role == "assistant" for m in messages),
                "canonical_sha256": _canonical_digest(messages),
                "first_ordinal": messages[0].ordinal if messages else None,
                "last_ordinal": messages[-1].ordinal if messages else None,
                "messages": len(messages),
                "output": str(args.output),
                "output_bytes": args.output.stat().st_size,
                "source_slices": len(sources),
                "user_messages": sum(m.role == "user" for m in messages),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
