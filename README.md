# Exchange Report Downloader Web

面向公网部署的 A 股 / 港股公告下载网站，仓库对应：

- 前端域名：`download.shijason.com`
- 后端域名：`api.shijason.com`
- GitHub 仓库：`JasonShi-hub/exchange-report-downloader-web`

## 目录结构

```text
frontend/                  GitHub Pages 静态站
backend/                   FastAPI 后端
.github/workflows/         GitHub Pages 自动部署
Dockerfile                 Koyeb 后端容器构建
.dockerignore              Koyeb 构建上下文裁剪
```

## 本地开发

### 1. 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ACCESS_PASSWORD='your-shared-password'
export TOKEN_SECRET='replace-with-a-long-random-secret'
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. 启动前端静态页

前端是纯静态文件，可直接用任意静态服务器：

```bash
cd frontend
python3 -m http.server 4173
```

本地开发时把 `frontend/app.js` 中的 `API_BASE` 暂时改为 `http://127.0.0.1:8000`。

## GitHub Pages 部署

1. 在 GitHub 新建仓库 `exchange-report-downloader-web`
2. 将本地代码推送到 `main`
3. 在仓库 `Settings -> Pages` 中把 source 设置为 `GitHub Actions`
4. 为仓库配置自定义域名 `download.shijason.com`
5. 在 DNS 中添加：

```text
CNAME download shijason.com -> JasonShi-hub.github.io
```

## Koyeb 部署

Koyeb 官方文档目前支持从 GitHub 仓库进行 git-driven 部署，也支持直接使用仓库根目录的 `Dockerfile` 构建容器。我这里已经给仓库补好了根目录 `Dockerfile`，因此在 Koyeb 控制台中直接选择这个 GitHub 仓库即可。参考：

- Koyeb 通用部署入口：[Quick Start](https://www.koyeb.com/docs/deploy)
- Koyeb Dockerfile / GitHub 部署方式：[Deploy a Rust App](https://www.koyeb.com/docs/deploy/rust)
- Koyeb 自定义域名：[Configure Custom Domains](https://www.koyeb.com/docs/run-and-scale/domains)
- Koyeb HTTP 健康检查：[Health Checks](https://www.koyeb.com/docs/run-and-scale/health-checks)

### 创建后端服务

1. 打开 Koyeb 控制台，创建 `Web Service`
2. 选择 `GitHub` 部署源
3. 选择仓库 `JasonShi-hub/exchange-report-downloader-web`
4. 分支选 `main`
5. Builder 选择 `Dockerfile`
6. 使用仓库根目录的 `Dockerfile`
7. Service 名称可设为 `exchange-report-downloader-api`
8. 实例先选免费档

### 环境变量

在 Koyeb 控制台设置以下环境变量：

```text
ACCESS_PASSWORD=你的共享密码
TOKEN_SECRET=一段足够长的随机字符串
ALLOWED_ORIGIN=https://download.shijason.com
```

建议同时保留默认值：

```text
JOB_RETENTION_SECONDS=3600
MAX_STOCKS_PER_JOB=5
MAX_DATE_RANGE_DAYS=365
MAX_QUEUED_JOBS=5
LOGIN_RATE_LIMIT_PER_MINUTE=12
JOB_RATE_LIMIT_PER_MINUTE=8
```

### 健康检查

Koyeb 默认会做 TCP 健康检查；如果要更稳，部署后把健康检查改成 HTTP：

```text
Path: /api/health
Method: GET
```

### 绑定后端域名

1. 在 Koyeb 控制台给这个 Service 添加自定义域名 `api.shijason.com`
2. Koyeb 会返回一个 `*.cname.koyeb.app` 的目标值
3. 在 DNS 中添加：

```text
CNAME api shijason.com -> <koyeb-provided-cname>
```

Koyeb 文档说明，自定义子域名应使用 `CNAME` 记录，TLS 证书会自动签发，通常几分钟内生效，极端情况下可能更久。

## 任务模型

- 全局单 worker，FIFO 队列
- 最多 1 个运行中任务
- 最多 5 个等待任务
- 单次最多 5 个股票代码
- 日期跨度最多 365 天
- ZIP 结果保留 1 小时

## 前端交互说明

- 默认交付：浏览器下载 ZIP
- 增强模式：支持 `showDirectoryPicker()` 的浏览器可将 ZIP 自动解压并写入用户选择的本地目录
- A 股不勾选类别时默认下载全部常规公告，不包含调研报告
- 前端默认请求地址固定为 `https://api.shijason.com`

## 测试

```bash
cd backend
python3 -m unittest discover -s tests
```

如果要运行 API 合约测试，需要先安装 `fastapi` 及其测试依赖。

## DNS 当前目标

前端：

```text
CNAME download shijason.com -> JasonShi-hub.github.io
```

后端：

```text
CNAME api shijason.com -> <koyeb-provided-cname>
```
