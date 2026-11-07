from __future__ import annotations

from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

try:
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover - older astrbot
    TextPart = None  # type: ignore

from .core.store import MemoryStore


def _data_root() -> Path:
    # 规范：data/plugin_data/<plugin_name>
    try:
        return StarTools.get_data_dir("astrbot_plugin_sytori_memory")
    except Exception:
        p = Path("data") / "plugin_data" / "astrbot_plugin_sytori_memory"
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()


def _blocklist(cfg: dict) -> list[str]:
    raw = str(cfg.get("ephemeral_blocklist") or "")
    return [x.strip() for x in raw.split(",") if x.strip()]


class SytoriMemoryPlugin(Star):
    """做梦记忆：四层长期记忆 + 做梦整理。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        logger.info("做梦记忆 plugin loaded")

    def _store(self, event: AstrMessageEvent) -> MemoryStore:
        return MemoryStore(_data_root(), event.unified_msg_origin)

    @filter.command("记忆帮助", alias={"sytori_help", "悟帮", "悟帮助"})
    async def cmd_help(self, event: AstrMessageEvent):
        """查看做梦记忆插件帮助"""
        yield event.plain_result(
            "做梦记忆\n"
            "/记住 <内容> — 写入精选笔记\n"
            "/回忆 <关键词> — 检索笔记/Wiki\n"
            "/做梦 — 离线整理（纠错/去重/晋升索引）\n"
            "/记忆索引 — 查看短索引\n"
            "Agent 工具：sytori_memorize / sytori_recall / sytori_dream"
        )

    @filter.command("记住", alias={"sytori_mem", "悟记"})
    async def cmd_memorize(self, event: AstrMessageEvent):
        """写入一条精选笔记。用法：/记住 内容"""
        text = (event.message_str or "").strip()
        # 去掉指令本身
        for prefix in ("记住", "悟记", "sytori_mem"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        if not text:
            yield event.plain_result("用法：/记住 值得长期记住的内容")
            return
        blocked = _blocklist(self.config)
        low = text.lower()
        if any(b.lower() in low for b in blocked):
            yield event.plain_result("这条更像临时状态，没写入精选笔记。可用 /做梦 后再整理。")
            return
        store = self._store(event)
        store.add_note(text, kind="note")
        yield event.plain_result(f"已写入精选笔记：{text[:120]}")

    @filter.command("回忆", alias={"sytori_recall", "悟忆"})
    async def cmd_recall(self, event: AstrMessageEvent, query: str = ""):
        """检索笔记与 Wiki。用法：/回忆 关键词"""
        q = (query or "").strip() or (event.message_str or "").strip()
        for prefix in ("回忆", "悟忆", "sytori_recall"):
            if q.startswith(prefix):
                q = q[len(prefix) :].strip()
                break
        store = self._store(event)
        hits = store.search(q, limit=6)
        if not hits:
            yield event.plain_result("没有找到相关记忆。")
            return
        lines = []
        for h in hits:
            lines.append(f"- [{h.get('kind')}] {h.get('content','')[:160]}")
        yield event.plain_result("检索结果：\n" + "\n".join(lines))

    @filter.command("做梦", alias={"sytori_dream", "dream"})
    async def cmd_dream(self, event: AstrMessageEvent):
        """离线做梦：去重、剔除 ephemeral、重建短索引"""
        store = self._store(event)
        report = store.dream(_blocklist(self.config))
        yield event.plain_result(
            "做梦完成：\n"
            f"- 保留笔记 {report['kept_notes']}\n"
            f"- 清理 {report['deleted']}\n"
            f"- Wiki 页 {report['wiki_pages']}\n"
            "短索引已重建。"
        )

    @filter.command("记忆索引", alias={"sytori_index", "悟索引"})
    async def cmd_index(self, event: AstrMessageEvent):
        """查看当前短索引"""
        store = self._store(event)
        max_chars = int(self.config.get("index_max_chars") or 1200)
        yield event.plain_result(store.read_index(max_chars=max_chars))

    @filter.on_llm_request()
    async def inject_index(self, event: AstrMessageEvent, req):
        """每次 LLM 请求前注入短索引（不进 system_prompt，避免破坏缓存）。"""
        if not bool(self.config.get("inject_index_on_llm", True)):
            return
        try:
            store = self._store(event)
            max_chars = int(self.config.get("index_max_chars") or 1200)
            idx = store.read_index(max_chars=max_chars).strip()
            if not idx or idx.count("\n") < 2:
                return
            block = (
                "<dream_memory_index>\n"
                f"{idx}\n"
                "</dream_memory_index>\n"
                "以上为长期记忆短索引；细节请用 sytori_recall 按需查找。"
            )
            if TextPart is not None and hasattr(req, "extra_user_content_parts"):
                part = TextPart(text=block)
                if hasattr(part, "mark_as_temp"):
                    part = part.mark_as_temp()
                req.extra_user_content_parts.append(part)
            else:
                # fallback：追加到 prompt 尾部（兼容旧版）
                if hasattr(req, "prompt") and isinstance(req.prompt, str):
                    req.prompt = (req.prompt or "") + "\n\n" + block
        except Exception as e:  # noqa: BLE001
            logger.warning(f"sytori inject_index failed: {e}")

    @filter.llm_tool(name="sytori_memorize")
    async def tool_memorize(self, event: AstrMessageEvent, content: str):
        """把值得跨会话保留的规则/偏好写入精选笔记。不要写入现价、资金费率、OI 等临时状态。

        Args:
            content(string): 要记住的内容，一句话为佳
        """
        store = self._store(event)
        blocked = _blocklist(self.config)
        if any(b.lower() in content.lower() for b in blocked):
            return "拒绝：内容像临时状态，未写入。"
        store.add_note(content, kind="note")
        return f"已记住：{content[:200]}"

    @filter.llm_tool(name="sytori_recall")
    async def tool_recall(self, event: AstrMessageEvent, query: str):
        """按关键词检索精选笔记与 Wiki。

        Args:
            query(string): 检索关键词
        """
        store = self._store(event)
        hits = store.search(query, limit=5)
        if not hits:
            return "无结果"
        return "\n".join(f"- [{h.get('kind')}] {h.get('content','')[:200]}" for h in hits)

    @filter.llm_tool(name="sytori_dream")
    async def tool_dream(self, event: AstrMessageEvent):
        """执行一次做梦整理：去重笔记、剔除临时状态、重建短索引。

        Args:
        """
        store = self._store(event)
        report = store.dream(_blocklist(self.config))
        return (
            f"dream ok kept={report['kept_notes']} deleted={report['deleted']} "
            f"wiki={report['wiki_pages']}"
        )

    async def terminate(self):
        logger.info("做梦记忆 plugin terminated")
