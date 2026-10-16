"""Autenticação, CSRF, criptografia de campos sensíveis e proteção contra força bruta."""
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, g, jsonify, redirect, request, session, url_for


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- CSRF ----------
def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def csrf_valido() -> bool:
    esperado = session.get("csrf", "")
    enviado = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not esperado or not enviado:
        return False
    return secrets.compare_digest(enviado.encode("utf-8"), esperado.encode("utf-8"))


# ---------- Criptografia (senhas de clientes) ----------
def _fernet() -> Fernet:
    return Fernet(current_app.config["FERNET_KEY"].encode())


def criptografar(texto: str) -> str:
    return _fernet().encrypt(texto.encode("utf-8")).decode()


def descriptografar(token: str):
    try:
        return _fernet().decrypt(token.encode()).decode("utf-8")
    except InvalidToken:
        return None


# ---------- Controle de acesso ----------
def eh_api() -> bool:
    return request.path.startswith("/api/")


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.get("user") is None:
            if eh_api():
                return jsonify(erro="Sessão expirada. Entre novamente."), 401
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.get("user") is None:
            return jsonify(erro="Sessão expirada. Entre novamente."), 401
        if g.user["role"] != "admin":
            return jsonify(erro="Apenas administradores podem executar esta ação."), 403
        return view(*a, **kw)
    return wrapper


def ip_cliente() -> str:
    return request.remote_addr or "?"


# ---------- Bloqueio de força bruta ----------
def _chave_tentativa(username: str) -> str:
    return f"{ip_cliente()}|{username.strip().lower()}"


def _limite_janela():
    minutos = current_app.config["LOGIN_JANELA_MIN"]
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).strftime("%Y-%m-%dT%H:%M:%SZ")


def login_bloqueado(db, username: str) -> bool:
    n = db.execute(
        "SELECT COUNT(*) FROM tentativas_login WHERE chave = ? AND criado_em >= ?",
        (_chave_tentativa(username), _limite_janela()),
    ).fetchone()[0]
    return n >= current_app.config["LOGIN_MAX_TENTATIVAS"]


def registrar_falha_login(db, username: str):
    db.execute("DELETE FROM tentativas_login WHERE criado_em < ?", (_limite_janela(),))
    db.execute("INSERT INTO tentativas_login (chave, criado_em) VALUES (?, ?)",
               (_chave_tentativa(username), agora_iso()))
    db.commit()


def limpar_falhas_login(db, username: str):
    db.execute("DELETE FROM tentativas_login WHERE chave = ?", (_chave_tentativa(username),))
    db.commit()
