# Mobile Use Web

[English](README.md) | 简体中文

## 📁 项目结构

```
src/
├── app/                    # Next.js 应用路由
│   ├── api/               # API 路由处理器
│   ├── chat/              # 聊天页面组件
│   ├── layout.tsx         # 根布局
│   ├── page.tsx          # 首页
│   └── globals.css       # 全局样式
├── components/            # 可重用 UI 组件
│   ├── ui/               # 基础 UI 组件 (shadcn/ui)
│   ├── chat/             # 聊天相关组件
│   ├── phone/            # 移动屏幕组件
│   ├── common/           # 通用工具组件
│   └── resize/           # 可调整大小面板组件
├── hooks/                # 自定义 React Hooks
├── lib/                  # 工具库
├── styles/               # 附加样式表
├── types/                # TypeScript 类型定义
└── assets/               # 静态资源
```

## 🚦 快速开始

### 先决条件

- Node.js >= 20
- npm 

### 开发

1. **导航到 web 目录**
   ```bash
   cd demohouse/mobile-use/web
   ```

2. **安装依赖**
   ```bash
   npm install
   ```

3. **配置环境变量**
   ```bash
   cp .env.example .env
   ```
   
   编辑 `.env` 并设置：
   ```env
   CLOUD_AGENT_BASE_URL=http://localhost:8000/mobile-use/
   ```

4. **启动开发服务器**
   ```bash
   npm run dev
   ```

5. **访问应用程序**
   在浏览器中打开 [http://localhost:8080?token=123456](http://localhost:8080?token=123456)

### 生产构建

```bash
# 构建生产版本
npm run build

# 启动生产服务器
npm run start
```

## 🔧 配置

### 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `CLOUD_AGENT_BASE_URL` | 后端代理服务 URL | 必需 |

### Next.js 配置

项目使用 Next.js 的独立输出模式用于容器化部署：

```typescript
const nextConfig: NextConfig = {
  output: "standalone",
};
```
