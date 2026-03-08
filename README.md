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
render.yaml                Render 部署配置
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

## Render 部署

1. 在 Render 中创建新 Web Service，并选择当前仓库
2. Render 会自动读取仓库根目录的 `render.yaml`
3. 在 Render 控制台设置环境变量：

```text
ACCESS_PASSWORD=你的共享密码
TOKEN_SECRET=一段足够长的随机字符串
ALLOWED_ORIGIN=https://download.shijason.com
```

4. 绑定自定义域名 `api.shijason.com`
5. 在 DNS 中添加：

```text
CNAME api shijason.com -> <render-assigned-domain>
```

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

## 测试

```bash
cd backend
python3 -m unittest discover -s tests
```

如果要运行 API 合约测试，需要先安装 `fastapi` 及其测试依赖。
