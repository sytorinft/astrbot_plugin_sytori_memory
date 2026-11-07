# astrbot_plugin_sytori_memory

**Sytori 悟·记忆** — AstrBot 长期记忆插件（四层 + 做梦）。

灵感来自 [Anthropic — The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory)。

## 四层

1. **Raw** — 会话原文摘要（按轮次落盘，可检索）
2. **Notes** — 精选笔记（用户偏好、规则、纠错）
3. **Wiki** — 互相关联的主题页
4. **Index** — 短索引，每次 LLM 请求前注入（保持精简）

## 指令

| 指令 | 说明 |
|---|---|
| `/悟记 内容` | 写入一条精选笔记 |
| `/悟忆 关键词` | 检索笔记 / wiki |
| `/做梦` | 离线做梦：纠错、合并、修剪、晋升索引 |
| `/悟索引` | 查看当前短索引 |
| `/悟帮` | 帮助 |

也可由 Agent 调用 LLM Tools：`sytori_memorize` / `sytori_recall` / `sytori_dream`。

## 数据目录

持久化在 AstrBot `data` 下（不在插件目录，避免更新覆盖）：

`data/sytori_memory/<umo_hash>/` → `index.md` `notes.jsonl` `wiki/` `raw/` `dream_log.jsonl`

## 安装

1. 将本仓库放入 `AstrBot/data/plugins/astrbot_plugin_sytori_memory`
2. WebUI → 插件 → 重载
3. （可选）配置 `_conf_schema.json` 中的注入开关与索引长度上限

## Logo

`logo.png` 1:1，推荐 256×256。市场徽标也可托管后填写公开 URL。

## License

MIT
