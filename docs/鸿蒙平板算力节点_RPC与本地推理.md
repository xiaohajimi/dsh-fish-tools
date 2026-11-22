# 鸿蒙平板当算力节点：RPC 与本地推理的实测对比

> 设备：华为 MatePad（11.9 GB 内存，8 核），HarmonyOS NEXT
> 主机：Ryzen 9 7845HX + RTX 5070 Laptop 8 GB
> 日期：2026-11-22 ~ 11-23
> 所有数字来自真机运行，不是估算。

## 一句话结论

**平板当 RPC 节点能跑，但慢到只有 PC CPU 的 1/54；同一台平板本地跑 1.5B 模型，比当 RPC 节点还快一倍。**

| 方式 | 模型 | 速度 | 备注 |
|---|---|---|---|
| 平板 RPC 节点 | Gemma-4 E4B Q4 | **0.22 tok/s** | prefill 2.80 s/token |
| 平板本地推理（4 线程，省电） | Qwen2.5-1.5B Q4 | **0.40 tok/s** | |
| 平板本地推理（8 线程，性能模式） | Qwen2.5-1.5B Q4 | **0.47 tok/s** | +17.5%，可能是噪声 |
| PC CPU（参照） | E4B Q4 | 11.97 tok/s | |
| PC GPU（参照） | E4B Q4 | 84.2 tok/s | |

## 做法：RPC 模式

1. 把 llama.cpp 的 `rpc-server` 编进 HAP（`GGML_RPC=ON`，并**显式链接 `ggml-rpc`**，否则报 `Failed to find RPC backend`）
2. PC 端 `hdc fport tcp:50052 tcp:50052`
3. `llama-server -m <模型> --rpc 127.0.0.1:50052 -ngl 99`

## 做法：本地推理模式（本次新增）

HAP 里加 NAPI：下载模型 → 加载 → 生成，**全部放工作线程**。

关键实现点：

```cpp
// 1) 沙箱：hdc file send 写不进 /data/app/.../files（permission denied）
//    → 让 App 自己用 HTTP 下载（原始 socket，HTTP/1.0 GET）
//    → 模型放 getContext(this).cacheDir

// 2) 主线程不能阻塞：同步下载 1 GB 会触发系统 THREAD_BLOCK_3S 冻结
//    → RunAllLocal() 只起 std::thread 后立即返回，UI 每秒轮询 localJob()

// 3) 鸿蒙 libcxx 的 <mutex> 在本工程编译不过（20 个错误）
//    → 用 std::atomic_flag 自己写自旋锁，不 include <mutex>

// 4) PC 防火墙挡入站 → 加规则要管理员
//    → 改用 hdc rport tcp:8000 tcp:8000，App 直接连 127.0.0.1:8000
```

## 编译踩坑清单

| 现象 | 根因 | 解法 |
|---|---|---|
| `Failed to find RPC backend` | 只开 `GGML_RPC=ON` 不够 | `target_link_libraries(... ggml-rpc)` |
| `error: unknown type name 'SpinLock'` | 替换代码段时把定义删了 | 定义放在使用点之前 |
| `<mutex>:219 unknown type name` | libcxx-ohos 与本工程参数冲突 | 自写自旋锁 |
| `spawn java ENOENT` | 打包要 JAVA_HOME | `JAVA_HOME=C:\DevEcoStudio\jbr` |
| App 界面卡死、日志 `THREAD_BLOCK_3S` | 下载/加载跑在 UI 线程 | 工作线程 + 轮询 |
| 下载 0 MB/0.0 MB/s | PC 防火墙挡入站 | `hdc rport` 反向转发 |

## 为什么 0.47 上不去

- 8 线程只比 4 线程快 17.5%，说明不是线程不够
- 1.5B Q4 在平板 0.47 tok/s，换算约 **每 token 2.1 秒**，这是 CPU 频率/ARM 路径优化的上限
- 想更快只能：更小的模型（E2B/Q4 以下）、或用 NPU（llama.cpp 目前不走 NPU）

## 复现步骤

```bash
# 1) 反向端口把模型送进平板
hdc rport tcp:8000 tcp:8000
python -m http.server 8000 --directory D:\share   # 放 model.gguf

# 2) App 里 URL 填 http://127.0.0.1:8000/model.gguf
# 3) 点"下载模型" → 等状态变成"完成"，读"速度"
```

## 结论建议

- **平板适合**：离线小模型问答（1.5B 以下，能接受 ~0.5 tok/s）
- **平板不适合**：当 PC 的算力扩展；RPC 模式比本地还慢
- **手机集群**：没有现成方案；llama.cpp RPC 是流水线并行，每加一台都要同步，速度不升反降
