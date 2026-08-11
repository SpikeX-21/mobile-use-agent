# Mobile Use Web

English | [简体中文](README_zh.md)

## 📁 Project Structure

```
src/
├── app/                    # Next.js app router
│   ├── api/               # API route handlers
│   ├── chat/              # Chat page component
│   ├── layout.tsx         # Root layout
│   ├── page.tsx          # Home page
│   └── globals.css       # Global styles
├── components/            # Reusable UI components
│   ├── ui/               # Base UI components (shadcn/ui)
│   ├── chat/             # Chat-specific components
│   ├── phone/            # Mobile screen components
│   ├── common/           # Common utility components
│   └── resize/           # Resizable panel components
├── hooks/                # Custom React hooks
├── lib/                  # Utility libraries
├── styles/               # Additional stylesheets
├── types/                # TypeScript type definitions
└── assets/               # Static assets
```

## 🚦 Quick Start

### Prerequisites

- Node.js >= 20
- npm package manager

### Installation

1. **Navigate to the web directory**
   ```bash
   cd demohouse/mobile-use/web
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set:
   ```env
   CLOUD_AGENT_BASE_URL=http://localhost:8000/mobile-use/
   ```

4. **Start development server**
   ```bash
   npm run dev
   ```

5. **Access the application**
   Open [http://localhost:8080?token=123456](http://localhost:8080?token=123456) in your browser

### Production Build

```bash
# Build for production
npm run build

# Start production server
npm run start
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLOUD_AGENT_BASE_URL` | Backend agent service URL | Required |

### Next.js Configuration

The project uses Next.js with standalone output for containerized deployments:

```typescript
const nextConfig: NextConfig = {
  output: "standalone",
};
```
