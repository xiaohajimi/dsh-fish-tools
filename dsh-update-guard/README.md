# dsh-update-guard · DSH 版本守卫

给 DeepSeek Harness 用的小插件：**记住当前版本，版本一变就告警，并提醒模型不要随手升级。**

## 为什么会有它

DSH 桌面版升级出过事故：升完打不开新对话，最后靠装回旧版覆盖才救回来。
教训是「升级前先备份、先记可用版本、想清楚再动」。

这个插件就是那条教训的执行器。

## 它做什么

1. **版本锁定**：第一次加载时把当前运行版本写进配置文件
2. **变更告警**：之后每次加载都比对；版本不一致就写一份告警文档（含回退路径与备份步骤），并在宿主日志打 error
3. **每轮提醒**：往系统提示注入一小节，提醒模型：用户提出升级 DSH 时先拦、先备份、先记版本路径

## 它不做什么

- **不阻止安装**。DSH 桌面版的依赖里没有自动更新组件（实测 `app.asar/package.json`，196 个依赖里没有 electron-updater / autoUpdater），更新只发生在用户手动点「设置 → 检查更新」之后。安装器一跑，插件拦不住。
- **不改系统配置**。只读安装目录的 `package.json`，只写自己的两个状态文件。
- **不自动回退**。回退是人的动作，插件只把路径和步骤摆出来。

## 安装

在工作区准备一个包目录：

```
dsh-update-guard/
  package.json
  cordis.patch.yml
  index.js
  locale/en.json
  locale/zh.json
  docs/DETAIL.md
  icon.svg
```

然后在 DSH 里用插件管理器安装这个目录（`install_bundle`，或「插件 → 添加插件」选择本地目录）。

## 配置

状态文件路径写死在代码里，按需改：

| 常量 | 默认 | 作用 |
|---|---|---|
| `LOCK` | `<你的目录>/DSH版本锁.json` | 锁定的版本 |
| `ALERT` | `<你的目录>/DSH版本变更告警.md` | 版本变化时写的告警 |

系统提示那一节的排序与名字可通过插件行 `config` 覆盖：

```yaml
- id: dsh-update-guard
  name: '@local/dsh-update-guard'
  config:
    order: 9100
    sectionName: user:update-guard
```

## 验证

- `index.js` 通过 `node --check`
- 安装后宿主日志出现 `update-guard:` 开头的行
- 想重置锁定：删掉锁文件，重启 DSH

## 已知限制

- 只认 `package.json` 里的 `version` 字段；版本号相同但内容被替换检测不到
- 不校验签名，不做完整性检查

## 许可

MIT
