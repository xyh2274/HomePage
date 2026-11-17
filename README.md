# HomePage

一个轻量级的 NAS 导航页，带可视化管理后台。

![导航页](https://cdn.jsdelivr.net/gh/xyh2274/tuchuang@9241860/HomePage/screenshot-light.webp)

服务列表存在 SQLite 里，通过 `/admin` 网页增删改，加一个服务不需要碰代码。前端是玻璃拟态风格，支持明暗双主题、图标自动抓取、服务在线状态。

---

## 特性

| | |
|---|---|
| **视觉保真** | 背景图 + 白相框照片 + 玻璃卡片 + 图标网格，与原始静态页一致 |
| **可视化管理** | `/admin` 增删改服务、拖排序、临时隐藏，改完刷新即生效 |
| **图标五级回退** | Font Awesome → 图片 URL → 上传 → 自动 favicon → 首字母 |
| **在线状态** | TCP 探测，绿点在跑 / 红点离线 / 灰点未探测 |
| **页面文案** | 两组诗歌 + 签名可在后台改，留空则整组隐藏 |
| **明暗双主题** | 跟随系统 + 手动切换，三页同步，记在 `localStorage` |
| **响应式** | 桌面左栏照片 / 平板手机顶部横条，全面屏安全区适配 |
| **轻量** | 约 45 MB 内存，无构建步骤，纯 HTML/CSS/JS |

## 截图

| 桌面 | 移动端 |
|---|---|
| ![桌面](https://cdn.jsdelivr.net/gh/xyh2274/tuchuang@9241860/HomePage/screenshot-light.webp) | ![移动端](https://cdn.jsdelivr.net/gh/xyh2274/tuchuang@9241860/HomePage/screenshot-mobile.webp) |

---

## 快速开始

```bash
git clone <this-repo>
cd HomePage
docker compose up -d --build
```

访问 `http://<NAS-IP>:8889`，管理后台在 `/admin`（宿主 8889 → 容器 8081）。

首次启动会自动建库并写入几条示例服务，可以直接在后台改成自己的。

### 环境要求

- Docker + Docker Compose
- 端口 `8889` 未被占用

---

## 配置

都在 `docker-compose.yml` 的 `environment` 里：

| 变量 | 默认 | 说明 |
|---|---|---|
| `ADMIN_PASSWORD` | `123456` | 管理后台密码。**建议改掉**，改完 `docker compose up -d` |
| `SECRET_KEY` | 固定值 | Flask session 签名。换了会导致登录失效，换机器部署建议重新生成 |
| `DATA_DIR` | `/data` | 数据库与上传文件位置 |
| `PORT` | `8081` | 容器内监听端口（宿主机映射见 ports） |
| `TZ` | `Asia/Shanghai` | 时区（影响日志时间） |

---

## 目录结构

```
HomePage/
├── app.py                  Flask 应用（路由 + API + 图标探测）
├── Dockerfile              python:3.11-alpine + gunicorn
├── docker-compose.yml
├── templates/
│   ├── index.html          导航页
│   ├── admin.html          管理后台
│   └── login.html          登录页
├── static/
│   ├── Selenabj.jpg        背景图
│   ├── Selena.jpg          原横图（竖屏横条用）
│   ├── side.jpg            预裁竖版（桌面左栏用）
│   ├── favicon.ico
│   └── style.css           原页面样式
├── legacy/                 原静态页备份，仅供对照
│   ├── index.html
│   └── main.js
└── data/                   运行时生成，已 gitignore
    ├── services.db
    └── uploads/
```

---

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/services` | 前台服务列表（仅 `enabled=1`） |
| GET | `/api/status` | 批量 TCP 探测，返回 `{id: true/false}` |
| GET | `/api/settings` | 页面文案（两组诗歌 + 签名） |
| PUT | `/api/admin/settings` | 更新文案（需登录） |
| GET | `/api/admin/services` | 全部服务（需登录） |
| POST | `/api/admin/services` | 新增 |
| PUT | `/api/admin/services/<id>` | 更新 |
| DELETE | `/api/admin/services/<id>` | 删除 |
| POST | `/api/admin/reorder` | 传 `{ids: [...]}` 重排 |
| POST | `/api/admin/upload-icon` | 上传图标（≤2MB） |
| GET | `/api/admin/probe-icon?url=` | 探测站点图标 |

---

## 几个设计说明

### 图标为什么不用浏览器直接取

浏览器请求 favicon 会被 **CORS、防盗链、http/https 混合内容**挡住。所以保存时后端先探一次（先试 `/favicon.ico`，再解析首页 `<link rel="icon">`，并用文件魔数校验），拿到就写进数据库。

三级回退：

```
① icon 有值  → fa-xxx 用 Font Awesome / URL 用图片
② 字段为空   → 浏览器请求 {服务域名}/favicon.ico
③ 加载失败   → 服务名首字母
```

### 图标网格按行均分

不是"塞满 N 个再换行"，而是按总数算每行几个：

```
7 个 → [4,3]      9 个 → [5,4]
8 个 → [4,4]     13 个 → [5,4,4]
```

先算行数 `ceil(n/max)`，再均摊余数，不会出现「6+1」那种孤零零的尾巴。每行独立 flex 居中，两行图标宽度一致。

### 主题为什么不用 JS 框架

CSS 变量 + `html[data-theme]` 就够了。首屏 `<script>` 在 CSS 之前执行读取 `localStorage`，避免闪白。

暗色不是简单反色：背景纱从「白 5%」变「黑 38%」，卡片从 `rgba(8,12,16,.14)` 变 `rgba(12,16,20,.52)`，主色也提亮一档（暗底上原色发闷）。

---

### 文案怎么改

进 `/admin`，第二张卡片「页面文案」里五个输入框：

| 字段 | 对应位置 |
|---|---|
| 诗一 · 英文 / 中文 | 卡片上第一组诗句 |
| 诗二 · 英文 / 中文 | 第二组（**两个都留空则整组不显示**） |
| 签名 | 卡片底部「他山之石，可以攻玉」那行 |

改完点「保存文案」，前台刷新即生效。文案存在 `settings` 表里，跟 `services` 一个数据库。

---

## 备份

只需备份 `data/`：

```bash
tar czf homepage-$(date +%F).tar.gz data/
```

`templates/`、`static/` 是源码的一部分，跟着 Git 走。

---

## 已知限制

- 状态探测是 TCP 连接，只能判断端口通不通，不知道服务是否健康
- 图标上传上限 2MB，不自动压缩
- 单用户密码认证，无多账号
