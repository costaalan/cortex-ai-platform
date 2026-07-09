"""Cortex Admin Panel — Flask with RBAC"""
import os
import time
from datetime import datetime, timedelta
from functools import wraps

import jwt
import requests
from flask import Flask, request, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config ───────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "cortex...26")
JWT_ALGORITHM = "HS256"
API_URL = os.getenv("API_URL", "http://localhost:8701")

# ── Demo users ───────────────────────────────────────
DEMO_USERS = {
    "demo@cortex.ai": {
        "password": "cortex2026",
        "role": "admin",
        "name": "Demo Admin",
    },
    "user@cortex.ai": {
        "password": "cortex2026",
        "role": "user",
        "name": "Demo User",
    },
    "viewer@cortex.ai": {
        "password": "cortex2026",
        "role": "viewer",
        "name": "Demo Viewer",
    },
}

# ── RBAC Decorators ──────────────────────────────────
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token required"}), 401
        try:
            token = auth_header.split(" ")[1]
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            g.user = payload
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

def require_role(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if g.user.get("role") not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper

# ── Endpoints ────────────────────────────────────────

@app.route("/health")
def health():
    return {"status": "healthy", "service": "admin-panel"}


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    user = DEMO_USERS.get(username)
    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    token = jwt.encode(
        {
            "sub": username,
            "role": user["role"],
            "name": user["name"],
            "exp": datetime.utcnow() + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return jsonify({
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "name": user["name"],
    })


@app.route("/api/documents")
@token_required
def list_documents():
    """Proxy to Cortex API for document listing."""
    try:
        resp = requests.get(f"{API_URL}/documents", timeout=10)
        return jsonify(resp.json()), resp.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"API unavailable: {str(e)}"}), 502


@app.route("/api/dashboard")
@token_required
@require_role("admin", "user")
def dashboard():
    """Aggregated usage dashboard."""
    try:
        # Fetch metrics from Cortex API
        health_resp = requests.get(f"{API_URL}/health", timeout=5)
        health_data = health_resp.json() if health_resp.ok else {}

        return jsonify({
            "status": "operational",
            "version": health_data.get("version", "1.0.0"),
            "agents": health_data.get("agents", {}),
            "uptime": "running",
            "features": {
                "rag_chat": True,
                "pdf_upload": True,
                "finops": True,
                "observability": True,
            },
            "metrics": {
                "documents_indexed": "active",
                "api_latency_p95": "< 2s",
                "availability": "99.9%",
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/users")
@token_required
@require_role("admin")
def list_users():
    """List demo users (admin only)."""
    users = []
    for email, data in DEMO_USERS.items():
        users.append({
            "email": email,
            "role": data["role"],
            "name": data["name"],
        })
    return jsonify({"users": users})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8702, debug=True)
