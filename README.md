# ⚡ Cortex AI Platform

**Plataforma corporativa de IA — RAG com citação de fontes, observabilidade e FinOps.**

[![CI/CD](https://github.com/costaalan/cortex-ai/actions/workflows/deploy.yml/badge.svg)](https://github.com/costaalan/cortex-ai/actions)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 🏗️ Arquitetura

```
                    ┌──────────────┐
                    │   Nginx :80  │  ← API Gateway, Rate Limit, CORS
                    └──────┬───────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │ Cortex API  │ │ Admin Panel │ │  Frontend   │
    │  :8701      │ │  :8702      │ │  SPA        │
    │  FastAPI    │ │  Flask      │ │  Vanilla JS │
    └──────┬──────┘ └─────────────┘ └─────────────┘
           │
    ┌──────┴──────────────────────────┐
    ▼                                 ▼
┌──────────┐              ┌───────────────────┐
│ChromaDB │              │ LangGraph Agents   │
│  :8001   │              │ Retriever→Validator│
│ Vector   │              │ →Orchestrator      │
└──────────┘              └───────────────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
┌─────────┐ ┌─────────┐
│Prometheus│ │ Grafana │
│  :9091   │ │  :3000  │
└─────────┘ └─────────┘
```

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/costaalan/cortex-ai.git
cd cortex-ai

# Deploy
docker compose up -d --build

# Verify
curl http://localhost:8701/health
```

**Acessos:**
- Frontend: `http://localhost`
- API Docs: `http://localhost/api/docs`
- Grafana: `http://localhost:3000` (admin/admin)
- Prometheus: `http://localhost:9091`

**Credenciais Demo:**
- Email: `demo@cortex.ai`
- Senha: `cortex2026`

## 📦 Serviços

| Serviço | Porta | Tecnologia | Descrição |
|---------|-------|------------|-----------|
| Cortex API | 8701 | FastAPI + LangGraph | Upload PDF, Chat RAG, agentes |
| Admin Panel | 8702 | Flask + JWT | RBAC, gestão de documentos |
| ChromaDB | 8001 | Chroma | Vector store |
| Prometheus | 9091 | Prometheus | Métricas |
| Grafana | 3000 | Grafana | Dashboards |
| Nginx | 80 | Nginx | API Gateway, proxy reverso |

## 🔧 API Endpoints

### Upload de Documentos
```bash
curl -X POST http://localhost:8701/upload \
  -F "file=@documento.pdf"
```

### Chat RAG
```bash
curl -X POST http://localhost:8701/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Quais são os direitos do titular?", "model": "ollama"}'
```

### FinOps — Comparativo de Custos
```bash
curl http://localhost:8701/finops/cost?tokens=1000000
```

### Health Check
```bash
curl http://localhost:8701/health
```

### Métricas Prometheus
```bash
curl http://localhost:8701/metrics
```

## 🤖 Agentes LangGraph

| Agente | Função |
|--------|--------|
| **RetrieverAgent** | Busca top-3 chunks no ChromaDB via embeddings |
| **ValidatorAgent** | Valida relevância e compliance dos chunks |
| **OrchestratorAgent** | Constrói resposta final com citação de fontes |

## 📊 Observabilidade

### Métricas Exportadas
- `cortex_chat_requests_total` — Total de requisições (por status)
- `cortex_chat_latency_seconds` — Histograma de latência
- `cortex_tokens_used_total` — Tokens consumidos
- `cortex_uploads_total` — Uploads realizados
- `cortex_agent_status` — Health dos agentes

### Grafana Dashboard
Dashboard pré-configurado com:
- Latência P95 do chat
- Consultas por minuto
- Tokens utilizados
- Status dos agentes (Retriever, Validator, Orchestrator)
- Requisições (sucesso vs erro)

## 💰 FinOps

Comparativo de custo por **1 milhão de tokens**:

| Provedor | Custo (BRL) | Economia vs OpenAI |
|----------|-------------|-------------------|
| **Ollama (Local)** | R$ 0,00 | R$ 15,00 |
| **DeepSeek** | R$ 0,50 | R$ 14,50 |
| **Anthropic Claude** | R$ 8,00 | R$ 7,00 |
| **OpenAI GPT-4o** | R$ 15,00 | — |

## 🧪 Testes

```bash
# API tests
cd api
pip install pytest httpx
python -m pytest test_main.py -v

# Integration test
curl -X POST http://localhost:8701/auth/login \
  -d "username=demo@cortex.ai&password=cortex2026"
```

## 🚢 Deploy

### Docker Compose
```bash
docker compose up -d --build
docker compose ps
docker compose logs -f cortex-api
```

### Cloudflare Tunnel
```bash
# Expor alancosta.dev/cortex → localhost:80
cloudflared tunnel run cortex-tunnel
```

### CI/CD (GitHub Actions)
O pipeline `.github/workflows/deploy.yml` executa:
1. Testes (pytest)
2. Build e push Docker images
3. Deploy automático na VPS

### AWS (conceitual)
Ver `terraform/main.tf` para arquitetura AWS com ECS Fargate, ALB, VPC, e CloudWatch.

## 📁 Estrutura de Diretórios

```
cortex/
├── docker-compose.yml        # Orquestração 6 containers
├── api/
│   ├── main.py               # FastAPI + LangGraph agents
│   ├── requirements.txt
│   └── Dockerfile
├── admin/
│   ├── app.py                # Flask RBAC
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   └── nginx.conf            # Rate limit, CORS, proxy
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   └── dashboards/
│       └── cortex.json       # Dashboard pré-configurado
├── frontend/
│   └── index.html            # SPA 3 páginas
├── .github/workflows/
│   └── deploy.yml            # CI/CD pipeline
├── terraform/
│   └── main.tf               # IaC conceitual AWS
└── README.md
```

## 📄 Licença

MIT © 2026 Alan Costa
