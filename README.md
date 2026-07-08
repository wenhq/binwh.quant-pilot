# binwh.quant-pilot

> **个人量化投研学习项目 · 代码由 AI 辅助生成**

- **后端**：FastAPI + SQLAlchemy async + MySQL + JWT
- **前端**：Vue 3 + TypeScript + Ant Design Vue + lightweight-charts
- **数据源**：akshare / baostock / 国信证券
- **ML**：scikit-learn + hmmlearn（PCA + HMM 市场状态识别）

## 快速启动

```bash
cd backend && pip install -r requirements.txt
cp .env.example .env   # 修改数据库连接和密钥
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

## 目录

```
├── backend/       # FastAPI 后端
├── frontend/      # Vue 3 前端
├── notebooks/     # Jupyter 学习笔记
└── docs/          # 设计文档
```

## 学习笔记

位于 `notebooks/` 目录，涵盖 Python 基础、NumPy/Pandas/SciPy、量化库（AKShare / Backtrader / PyFolio）、期权定价、Seaborn 可视化等内容。
