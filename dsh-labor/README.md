# dsh-labor · 本地派活

给 DeepSeek Harness 用的插件：**把机械活直接派给本地小模型，用工具调用的方式，不必手动起服务、手动贴结果。**

## 为什么会有它

跑本地小模型的人常遇到同一个问题：模型下载好了，但每次要用都得手动起服务、手动发请求、手动把结果复制回文件。省下来的时间又花在搬运上。

这个插件把那三步压成一次工具调用。

## 它提供什么

| 工具 | 作用 |
|---|---|
| `labor_status` | 看配置里的几只模型谁在跑、端口、配置文件是否读到 |
| `labor_start` | 后台起一只（spawn `llama-server`，日志落盘），60 秒内会回就绪状态 |
| `labor_ask` | 派一段活拿回答案（正文为空时自动回落 `reasoning_content`） |
| `labor_write` | 让它写代码**直接落盘**，返回路径 + 前 12 行预览，省一次复制粘贴 |

## 配置

插件读一个 JSON 配置，路径默认 `<工作区>/配置/labor.json`，也可用环境变量 `LABOR_CONFIG` 指到别处。文件不存在就回落到内置默认（三只占位）。

```json
{
  "server": "C:\\\\path\\\\to\\\\llama-server.exe",
  "presets": {
    "xiao": {
      "label": "Small model",
      "port": 8081,
      "model": "C:\\\\models\\\\small-Q6_K.gguf",
      "mmproj": "C:\\\\models\\\\mmproj-BF16.gguf",
      "ctx": 16384
    },
    "da": { "label": "Big model", "port": 8082, "model": "C:\\\\models\\\\big-Q4_0.gguf", "ctx": 8192 },
    "qwen": { "label": "Reasoner", "port": 8083, "model": "C:\\\\models\\\\r1.gguf", "ctx": 8192 }
  }
}
```

要点：

- 三只是**默认代号**，可以整组替换（配置文件里写什么就有什么）
- `mmproj` 可省略（纯文本模型）
- 一次只起一只：显存有限时这是刻意的约束

## 安装

把包目录放进工作区，用插件管理器安装该目录（`install_bundle`，或「插件 → 添加插件」选本地目录）。

修改 `index.js` 或配置文件后需要重启 DSH 才生效（目录链接安装不会热重载）。

## 边界与诚实说明

- `labor_write` 只允许写配置文件里指定的根目录之外的路径会被拒绝（代码里做了前缀检查，按需改成你的目录）
- 小模型只适合「有样可抄」的活。实测一个 8B 级模型在 100 道算法题上通过 39%，难题档只有 41.7%——**不要指望它写没见过的算法**
- 派回来的代码必须自己验收：语法、函数名、边界条件
- `labor_start` 起的是独立后台进程；训练/推理抢显存时会被驱动复位，别和训练同时跑

## 验证

- `index.js` 通过 `node --check`
- 起一只后 `labor_status` 显示在跑
- 一次 `labor_ask` 通得过 HTTP 200 与文本返回

## 许可

MIT
