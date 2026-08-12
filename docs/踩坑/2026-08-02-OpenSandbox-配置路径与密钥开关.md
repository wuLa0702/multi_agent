# 教训：OpenSandbox server 配置路径与密钥开关

> 📋 **规范**：遵循 `docs/2026-08-02-文档规范.md`
> 📌 **更新时间**：2026-08-02
> 📝 **版本变更记录**（永久保存，只追加不删除）：

> | 版本 | 日期 | 具体改动（精确到二级标题） |
> |------|------|------|
> | v1 | 2026-08-02 | 初版：记录 OpenSandbox 本地启动两个坑（配置路径 + api_key 开关） |

> **目录**：
> - § 现象
> - § 根因
> - § 修复与沉淀

---

## 现象

本地 `docker compose up opensandbox` 后容器**无限重启**（exit code 1），日志：

```
Creating sandbox service with type: kubernetes
Failed to initialize Kubernetes client: Invalid kube-config file.
```

本地根本没装 K8s，为什么走 k8s？

## 根因（两个坑叠加）

### 坑 1：配置挂载路径无效

镜像**内置**了默认配置并强制读取：

```
Env:  SANDBOX_CONFIG_PATH=/etc/opensandbox/config.toml
Cmd:  opensandbox-server --config /etc/opensandbox/config.toml
```

- 把 sandbox.toml 挂到 `~/.sandbox.toml`（`/root/.sandbox.toml`）**完全无效**——server 根本不读那里
- 配置文件缺失 → 走镜像默认配置 → `[runtime].type` 默认 `kubernetes` → 无 kube-config → 崩

**修复**：挂载覆盖镜像默认路径：

```yaml
volumes:
  - ./deploy/opensandbox/sandbox.toml:/etc/opensandbox/config.toml:ro
```

### 坑 2：api_key 为空拒绝启动（非交互模式）

配置读对了（`type: docker`）后，又卡启动：

```
Startup blocked: server.api_key is empty in non-interactive mode.
Set OPENSANDBOX_INSECURE_SERVER=YES to acknowledge the risk.
```

**修复**：本地开发加环境变量（官方 issue #750 的明确开关）：

```yaml
environment:
  - OPENSANDBOX_INSECURE_SERVER=YES   # 本地无 api_key；生产配 key 后关闭
```

## 修复与沉淀

- `docker-compose.yml`：①配置挂载改 `/etc/opensandbox/config.toml` ②本地加 `OPENSANDBOX_INSECURE_SERVER=YES` ③redis 对外端口 6398（对齐 .env.dev，避开 Clowder 6399）
- 验证：`Loaded configuration from /etc/opensandbox/config.toml` → `type: docker` → `Uvicorn running on 0.0.0.0:8080`
- 上云生产时：**必须配 `server.api_key`**（或 `OPENSANDBOX_API_KEY`），insecure 开关只限本地
