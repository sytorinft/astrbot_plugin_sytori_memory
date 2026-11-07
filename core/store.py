"""四层记忆存储。数据落在 AstrBot data 目录，避免插件更新被覆盖。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


def _safe_umo(umo: str) -> str:
    return hashlib.sha1((umo or "default").encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    def __init__(self, data_root: Path, umo: str):
        self.root = Path(data_root) / _safe_umo(umo)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "wiki").mkdir(exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        self.index_path = self.root / "index.md"
        self.notes_path = self.root / "notes.jsonl"
        self.dream_log = self.root / "dream_log.jsonl"
        if not self.index_path.exists():
            self.index_path.write_text(
                "# Sytori Index（保持精简）\n\n## Standing rules\n\n## Topics\n\n",
                encoding="utf-8",
            )

    def read_index(self, max_chars: int = 1200) -> str:
        text = self.index_path.read_text(encoding="utf-8")
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n…(truncated)"
        return text

    def write_index(self, text: str) -> None:
        self.index_path.write_text(text.strip() + "\n", encoding="utf-8")

    def add_note(
        self,
        content: str,
        *,
        kind: str = "note",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        item = {
            "ts": int(time.time()),
            "kind": kind,
            "tags": tags or [],
            "content": content.strip(),
        }
        with self.notes_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def list_notes(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.notes_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.notes_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:]

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return self.list_notes(limit=limit)[::-1][:limit]
        keys = [k for k in re.split(r"\s+", q) if k]
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in self.list_notes(limit=500):
            blob = (row.get("content") or "").lower()
            score = sum(1 for k in keys if k in blob)
            if score:
                scored.append((score, row))
        # wiki pages
        for p in sorted((self.root / "wiki").glob("*.md")):
            text = p.read_text(encoding="utf-8")
            blob = text.lower()
            score = sum(1 for k in keys if k in blob)
            if score:
                scored.append(
                    (
                        score,
                        {
                            "ts": int(p.stat().st_mtime),
                            "kind": "wiki",
                            "tags": [p.stem],
                            "content": text[:500],
                        },
                    )
                )
        scored.sort(key=lambda x: (-x[0], -x[1].get("ts", 0)))
        return [r for _, r in scored[:limit]]

    def upsert_wiki(self, slug: str, body: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff\-]+", "_", slug).strip("_") or "topic"
        path = self.root / "wiki" / f"{safe}.md"
        path.write_text(body.strip() + "\n", encoding="utf-8")
        # ensure index points to it
        idx = self.index_path.read_text(encoding="utf-8")
        marker = f"- [{safe}](wiki/{safe}.md)"
        if marker not in idx:
            if "## Topics" not in idx:
                idx += "\n## Topics\n"
            idx = idx.rstrip() + f"\n{marker}\n"
            self.write_index(idx)
        return path

    def append_raw(self, summary: str) -> Path:
        day = time.strftime("%Y%m%d")
        path = self.root / "raw" / f"{day}.jsonl"
        item = {"ts": int(time.time()), "summary": summary.strip()}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return path

    def dream(self, ephemeral_blocklist: list[str]) -> dict[str, Any]:
        """轻量做梦：去重笔记、剔除 ephemeral、压缩索引 standing rules。"""
        notes = self.list_notes(limit=1000)
        kept: list[dict[str, Any]] = []
        seen: set[str] = set()
        deleted = 0
        for n in notes:
            c = (n.get("content") or "").strip()
            if not c:
                deleted += 1
                continue
            low = c.lower()
            if any(b.lower() in low for b in ephemeral_blocklist if b.strip()):
                deleted += 1
                continue
            key = re.sub(r"\s+", " ", low)
            if key in seen:
                deleted += 1
                continue
            seen.add(key)
            kept.append(n)

        # rewrite notes.jsonl
        tmp = self.notes_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for n in kept:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        tmp.replace(self.notes_path)

        # promote: take last up-to-5 durable rules into index standing section
        rules = [n["content"] for n in kept if n.get("kind") in ("note", "rule")][-5:]
        idx_lines = ["# Sytori Index（保持精简）", "", "## Standing rules"]
        for r in rules:
            idx_lines.append(f"- {r[:160]}")
        idx_lines.append("")
        idx_lines.append("## Topics")
        for p in sorted((self.root / "wiki").glob("*.md")):
            idx_lines.append(f"- [{p.stem}](wiki/{p.stem}.md)")
        idx_lines.append("")
        self.write_index("\n".join(idx_lines))

        report = {
            "kept_notes": len(kept),
            "deleted": deleted,
            "wiki_pages": len(list((self.root / "wiki").glob("*.md"))),
            "ts": int(time.time()),
        }
        with self.dream_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
        return report
