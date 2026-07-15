# 红果短剧 去强制更新 — 项目总结

> 日期: 2026-07-15
> 仓库: callacat/gha-build-farm (GHA 构建 + 补丁)
> 目标: 移除红果免费短剧 (com.phoenix.read) 修改版的黑产强制更新弹窗

---

## 1. 问题概述

红果免费短剧修改版内嵌了第三方（黑产）的强制更新系统，在启动后数秒内弹出"温馨提示"对话框，要求用户"立即更新"跳转至夸克网盘下载新版。该弹窗无法关闭，影响正常使用。

## 2. 架构分析

### 更新链路

```
App 启动
  ↓
MainFragmentActivity.onCreate()
  ↓
ic.smali 方法 a() → new Socket(oneseeker.top:10008)   ← 同步阻塞连接
  ↓
检查更新结果
  ├─ 连接成功 + 服务器返回"有更新" → AlertDialog 弹窗
  ├─ 连接成功 + 服务器返回"无更新" → 放行
  ├─ 连接超时/网络不通           → 放行
  └─ 连接被拒/异常               → 卡启动页 (死锁)
```

### 关键发现

| 发现 | 说明 |
|------|------|
| **更新域名** | `oneseeker.top:10008` — 硬编码在 smali 中 (端口来自字节 CDN 动态配置) |
| **后备域名** | `sg-datahub.changzhi.top` (47.245.87.130, 阿里云新加坡) |
| **域名位置** | `smali_classes29/com/iC.smali:269`（裸域名 + 10008 端口） |
| | `smali_classes30/.../MainFragmentActivity.smali:56416`（`https://remote.oneseeker.top/appUpdate`）|
| **更新逻辑** | 在 Java 层通过 `ic.smali` 的 `a()Ljava/net/Socket;` 方法发起 Socket 连接 |
| **弹窗实现** | 字节跳动 LuckyDog 插件通道 或 `PopDefiner.force_upgrade_dialog` |
| **弹窗文案** | 服务器动态下发（不在 APK 中硬编码） |
| **网络特征** | 不走 DNS（硬编码 IP），但域名出现在 Mihomo 日志中 |
| **Xray 干扰** | 开启 Xray TUN 模式时流量被代理，错误判断为字节 CDN 流量 |

### 失败尝试清单

| 方案 | 结果 | 原因 |
|------|------|------|
| 域名毒化 `→ 127.0.0.1` | ❌ 卡启动页 | TCP RST 被识别为"服务器异常" |
| 域名毒化 `→ 1.1.1.1` | ❌ 卡启动页 | HTTP/HTTPS 超时导致同步阻塞死锁 |
| 域名毒化 `→ 0.0.0.0` | ❌ 卡启动页 | 同 RST 问题 |
| 域名毒化 `→ ldmnq.com` | ❌ 卡启动页 | 端口 10008 不通导致异常 |
| NOP `ic.smali` 方法体 | ❌ 编译失败/运行时崩溃 | `.end method` 重复 + 返回类型不匹配 |
| iptables 封 IP | ⚠️ 临时有效 | 不清数据时有效，清数据重装后无效（流量经过 Windows 主机） |

## 3. 最终解决方案 (v23)

**核心思路**：不替换域名，而是**把 `const-string` 的内容清空为空字符串**。

### 修改内容

**脚本**: `hg-plan-b.py`

```python
# 在 const-string 行中，把 oneseeker.top 替换为空字符串
const-string vX, ""  # empty: oneseeker blocked
```

**被修改的文件**:
| 文件 | 行号 | 原始内容 | 修改后 |
|------|------|---------|--------|
| `smali_classes29/com/iC.smali` | 269 | `const-string v10, "oneseeker.top"` | `const-string v10, ""` |
| `smali_classes30/.../MainFragmentActivity.smali` | 56416 | `const-string v13, "https://remote.oneseeker.top/appUpdate"` | `const-string v13, ""` |

### 原理

```
oneseeker.top = "" → URL构造失败 → MalformedURLException
  → 被 app 的 try-catch 捕获
  → 视为"检查更新请求失败"
  → 走"无更新"路径
  → 正常进入主界面 + 无弹窗
```

### 验证结果

- ✅ 安装后正常启动（不卡）
- ✅ 无更新弹窗
- ✅ 清理数据后启动正常
- ✅ 长期使用正常

## 4. 架构决策

### 为什么 NOP 方法体不行

`ic.smali` 中的方法 `a()Ljava/net/Socket;` 返回 Socket 对象。直接 NOP 为 `return-void` 导致 VerifyError，NOP 为 `return-object null` 导致调用方拿到 null 后空指针异常。且方法体超过 300 行 + 嵌套 `.method`，直接替换破坏结构。

### 为什么域名替换不行

App 同步阻塞式网络连接 (`Socket.connect()`)，无论指向什么 IP（127.0.0.1/1.1.1.1/ldmnq.com），只要连接无法建立就会一直阻塞，导致启动卡死。清空字符串让 URL 构造阶段就抛出异常，避免进入网络连接阶段。

### 为什么端口号搜不到

端口 `10008` 不在 smali 中，来自字节跳动 CDN 下发的 Gecko 配置文件（`bytegecko.com` 等域名）。App 先正常连接字节 CDN，从配置中获得 `oneseeker.top:10008` 后再发起二次连接。

## 5. 可复用的脚本

| 脚本 | 用途 |
|------|------|
| `hg-plan-b.py` | **核心补丁** — 清空指定的 const-string (通用: 修改 TARGETS 列表即可用于其他域名) |
| `hg-smali-patch.py` | 域名毒化 / checkUpdate 禁用 |
| `hg-update-patch.py` | AlertDialog.show() NOP |
| `hg-search-all-files.py` | 在 APK 所有文件中搜索关键词 |
| `hg-find-dialog.py` | 查找弹窗文本来源 |
| `hg-find-update-string.py` | 搜索更新相关字符串 |

## 6. 后续维护注意事项

1. **APK 版本升级后**，先跑 `analysis` 模式确认 `oneseeker.top` 是否在新版 smali 中存在
2. `ic.smali` 类名可能混淆变化，用 `hg-search-all-files.py` 搜索 `oneseeker` 定位新位置
3. 如果黑产更换域名，在 `hg-plan-b.py` 的 `TARGETS` 列表中添加新域名
4. 域名毒化 (`hg-smali-patch.py`) 仅作为辅助手段保留
5. **端口号无法通过 APK patch 完全封堵**（来自 CDN 配置），需要确保域名层封堵
