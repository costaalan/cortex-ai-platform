"""Cortex AI Platform — FastAPI Core Service"""
import os
import uuid
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

import jwt
import pypdf
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import prometheus_client
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from sentence_transformers import SentenceTransformer
import chromadb

# ── App ──────────────────────────────────────────────
app = FastAPI(
    title="Cortex AI Platform",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# ── Prometheus Metrics ───────────────────────────────
CHAT_REQUESTS = Counter(
    "cortex_chat_requests_total",
    "Total chat requests",
    ["status", "provider", "model"],
)
CHAT_LATENCY = Histogram(
    "cortex_chat_latency_seconds",
    "Chat latency in seconds",
    ["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
TOKENS_USED = Counter(
    "cortex_tokens_used_total",
    "Total tokens used",
    ["provider", "model"],
)
UPLOAD_COUNT = Counter(
    "cortex_uploads_total",
    "Total document uploads",
    ["project"],
)
AGENT_STATUS = Gauge(
    "cortex_agent_status",
    "Agent health (1=healthy)",
    ["agent"],
)
# FinOps — custo estimado em centavos de Real (R$)
COST_ESTIMATED = Counter(
    "cortex_cost_estimated_centavos",
    "Custo estimado em centavos (dividir por 100 para R$)",
    ["provider", "model"],
)

# ── Config ───────────────────────────────────────────
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
JWT_SECRET = os.getenv("JWT_SECRET", "cortex-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Inicializar métricas para que apareçam no /metrics (Prometheus só expõe métricas já usadas)
for agent in ["retriever", "validator", "orchestrator"]:
    AGENT_STATUS.labels(agent=agent).set(1)
for provider in ["anthropic", "openai"]:
    for model in ["claude-sonnet-4", "gpt-4o"]:
        CHAT_REQUESTS.labels(status="success", provider=provider, model=model).inc(0)
        CHAT_REQUESTS.labels(status="error", provider=provider, model=model).inc(0)
        TOKENS_USED.labels(provider=provider, model=model).inc(0)
        COST_ESTIMATED.labels(provider=provider, model=model).inc(0)
for project in ["cortex-api", "sprint-health", "skill-graph", "hr-onboarding"]:
    UPLOAD_COUNT.labels(project=project).inc(0)

# ── Models ───────────────────────────────────────────
embedder = SentenceTransformer("all-MiniLM-L6-v2")

_chroma_client = None
_collection = None

def get_chroma_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        _collection = _chroma_client.get_or_create_collection(
            name="cortex_docs",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection

# ── Pydantic Schemas ─────────────────────────────────
class ChatRequest(BaseModel):
    query: str
    model: str = "ollama"  # ollama | deepseek | openai | anthropic

class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    tokens_used: int
    model: str
    latency_ms: float

class HealthResponse(BaseModel):
    status: str
    version: str
    agents: dict

# ── Auth ─────────────────────────────────────────────
def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Extract user from JWT bearer token (optional for demo endpoints)."""
    if credentials is None:
        return {"sub": "anonymous", "role": "user"}
    return decode_token(credentials.credentials)

# ── Guardrails Config ─────────────────────────────────
MIN_RELEVANCE_SCORE = 0.5     # cosine distance threshold (menor = mais similar)
MAX_CONSECUTIVE_FAILURES = 3  # circuit breaker
FAILURE_COUNTS = {"retriever": 0, "validator": 0, "orchestrator": 0}
CIRCUIT_OPEN = {"retriever": False, "validator": False, "orchestrator": False}
import re

# PII filter pattern
PII_PATTERNS = [
    (re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b'), '[CPF REMOVIDO]'),
    (re.compile(r'\b\d{11}\b'), '[CPF REMOVIDO]'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[EMAIL REMOVIDO]'),
    (re.compile(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}'), '[TELEFONE REMOVIDO]'),
]

def sanitize_output(text: str) -> str:
    """Remove PII do texto gerado."""
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    query: str
    model: str
    documents: list
    validated_docs: list
    answer: str
    sources: list
    tokens: int

# ── Retriever Agent ─────
def retriever_agent(state: AgentState) -> AgentState:
    """Search ChromaDB for top-3 relevant chunks."""
    AGENT_STATUS.labels(agent="retriever").set(1)
    try:
        query_embedding = embedder.encode(state["query"]).tolist()
        col = get_chroma_collection()
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=3,
        )
        docs = []
        for i, (doc, meta) in enumerate(zip(
            results.get("documents", [[]])[0],
            results.get("metadatas", [[]])[0],
        )):
            if doc:
                docs.append({"content": doc, "metadata": meta, "score": float(
                    results.get("distances", [[0]])[0][i]
                )})
        state["documents"] = docs
        return state
    except Exception as e:
        AGENT_STATUS.labels(agent="retriever").set(0)
        state["documents"] = []
        return state

# ── Validator Agent ─────
def validator_agent(state: AgentState) -> AgentState:
    """Validate retrieved documents for compliance, relevance score, and content length."""
    AGENT_STATUS.labels(agent="validator").set(1)
    try:
        validated = []
        for doc in state.get("documents", []):
            content = doc.get("content", "")
            score = doc.get("score", 1.0)
            if len(content) > 50 and score < MIN_RELEVANCE_SCORE:
                validated.append(doc)
        state["validated_docs"] = validated
        FAILURE_COUNTS["validator"] = 0
        return state
    except Exception:
        AGENT_STATUS.labels(agent="validator").set(0)
        FAILURE_COUNTS["validator"] += 1
        state["validated_docs"] = []
        return state

# ── Orchestrator Agent ───
def orchestrator_agent(state: AgentState) -> AgentState:
    """Build final answer with source citations."""
    AGENT_STATUS.labels(agent="orchestrator").set(1)
    try:
        docs = state.get("validated_docs", [])
        if not docs:
            state["answer"] = "Nenhum documento relevante encontrado para sua consulta."
            state["sources"] = []
            state["tokens"] = 0
            return state

        # Build context from chunks
        context_parts = []
        sources = []
        for i, doc in enumerate(docs):
            source_info = {
                "index": i + 1,
                "source": doc.get("metadata", {}).get("source", "Desconhecido"),
                "page": doc.get("metadata", {}).get("page", "N/A"),
                "excerpt": doc["content"][:200] + "...",
            }
            sources.append(source_info)
            context_parts.append(f"[Fonte {i+1}] {doc['content']}")

        context = "\n\n".join(context_parts)
        query = state["query"]

        # Simulated LLM call — in production, call actual model
        answer = (
            f"Com base nos documentos analisados:\n\n{context[:500]}...\n\n"
            f"Resposta: Os documentos indicam informações relevantes sobre '{query}'. "
            f"Consulte as fontes citadas para detalhes completos."
        )
        tokens_estimate = len(context.split()) + len(answer.split())

        state["answer"] = answer
        state["sources"] = sources
        state["tokens"] = tokens_estimate
        return state
    except Exception as e:
        AGENT_STATUS.labels(agent="orchestrator").set(0)
        FAILURE_COUNTS["orchestrator"] += 1
        state["answer"] = f"Erro ao processar consulta: {str(e)}"
        state["sources"] = []
        state["tokens"] = 0
        return state

# ── Build LangGraph ──────
workflow = StateGraph(AgentState)
workflow.add_node("retriever", retriever_agent)
workflow.add_node("validator", validator_agent)
workflow.add_node("orchestrator", orchestrator_agent)
workflow.set_entry_point("retriever")
workflow.add_edge("retriever", "validator")
workflow.add_edge("validator", "orchestrator")
workflow.add_edge("orchestrator", END)
agent_graph = workflow.compile()

# ── TEXT CHUNKING ────────────────────────────────────
def chunk_text(text: str, chunk_size: int = 1000) -> list[str]:
    """Split text into chunks of ~1000 tokens (approximated by words)."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
    return chunks

# ── Endpoints ────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        agents={
            "retriever": "healthy",
            "validator": "healthy",
            "orchestrator": "healthy",
        },
    )

@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=prometheus_client.generate_latest(), media_type="text/plain; charset=utf-8")


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload PDF, chunk, embed, and store in ChromaDB."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    file_path = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    content = await file.read()
    file_path.write_bytes(content)

    try:
        # Extract text
        reader = pypdf.PdfReader(str(file_path))
        full_text = ""
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                full_text += f"\n--- Página {page_num + 1} ---\n{page_text}"

        if not full_text.strip():
            raise HTTPException(400, "Could not extract text from PDF")

        # Chunk
        chunks = chunk_text(full_text, chunk_size=1000)
        if not chunks:
            chunks = [full_text[:1000]]

        # Embed and store
        embeddings = embedder.encode(chunks).tolist()
        ids = [hashlib.md5(chunk.encode()).hexdigest()[:16] for chunk in chunks]
        metadatas = [
            {
                "source": file.filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "uploaded_by": user.get("sub", "anonymous"),
            }
            for i in range(len(chunks))
        ]

        col = get_chroma_collection()
        col.add(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        UPLOAD_COUNT.inc()
        file_path.unlink()  # cleanup

        return {
            "status": "success",
            "filename": file.filename,
            "chunks_indexed": len(chunks),
            "pages": len(reader.pages),
        }

    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(500, f"Processing error: {str(e)}")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """RAG chat endpoint with LangGraph pipeline."""
    t_start = time.time()

    CHAT_REQUESTS.labels(status="success").inc()

    try:
        state: AgentState = {
            "query": request.query,
            "model": request.model,
            "documents": [],
            "validated_docs": [],
            "answer": "",
            "sources": [],
            "tokens": 0,
        }

        result = agent_graph.invoke(state)
        latency = (time.time() - t_start) * 1000

        CHAT_LATENCY.observe(latency / 1000)
        TOKENS_USED.inc(result.get("tokens", 0))

        # Sanitize PII from answer
        clean_answer = sanitize_output(result["answer"])
        
        return ChatResponse(
            answer=clean_answer,
            sources=result["sources"],
            tokens_used=result["tokens"],
            model=request.model,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        CHAT_REQUESTS.labels(status="error").inc()
        raise HTTPException(500, f"Chat error: {str(e)}")


@app.post("/auth/login")
async def login(username: str, password: str):
    """Demo authentication endpoint."""
    # Demo credentials
    if username == "demo@cortex.ai" and password == "cortex2026":
        token = jwt.encode(
            {
                "sub": username,
                "role": "admin",
                "exp": datetime.utcnow() + timedelta(hours=24),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        return {"access_token": token, "token_type": "bearer", "role": "admin"}
    elif username == "viewer@cortex.ai" and password == "cortex2026":
        token = jwt.encode(
            {
                "sub": username,
                "role": "viewer",
                "exp": datetime.utcnow() + timedelta(hours=24),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        return {"access_token": token, "token_type": "bearer", "role": "viewer"}
    raise HTTPException(401, "Invalid credentials")


@app.get("/documents")
async def list_documents(user: dict = Depends(get_current_user)):
    """List indexed documents."""
    try:
        col = get_chroma_collection()
        results = col.get()
        docs = []
        seen_sources = set()
        for meta in results.get("metadatas", []):
            source = meta.get("source", "unknown")
            if source not in seen_sources:
                seen_sources.add(source)
                docs.append({
                    "source": source,
                    "chunks": results["metadatas"].count(meta),
                    "uploaded_by": meta.get("uploaded_by", "unknown"),
                })
        return {"documents": docs}
    except Exception as e:
        raise HTTPException(500, f"Error listing documents: {str(e)}")


@app.get("/finops/cost")
async def finops_cost(tokens: int = 1_000_000):
    """Simulate cost comparison across providers."""
    providers = {
        "Ollama (Local)": {"cost_per_1m": 0.00, "currency": "BRL"},
        "DeepSeek": {"cost_per_1m": 0.50, "currency": "BRL"},
        "OpenAI GPT-4o": {"cost_per_1m": 15.00, "currency": "BRL"},
        "Anthropic Claude": {"cost_per_1m": 8.00, "currency": "BRL"},
    }
    result = {}
    for name, info in providers.items():
        total = (tokens / 1_000_000) * info["cost_per_1m"]
        result[name] = {
            "tokens": tokens,
            "cost": round(total, 2),
            "currency": info["currency"],
            "savings_vs_openai": round(15.00 - info["cost_per_1m"], 2) if name != "OpenAI GPT-4o" else 0,
        }
    return {"tokens": tokens, "providers": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8701)
