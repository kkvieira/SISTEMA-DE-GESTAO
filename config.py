"""Configuração central da aplicação.

Segredos (SECRET_KEY e FERNET_KEY) vêm do arquivo `.env`. Se não existirem,
são gerados automaticamente na primeira execução e gravados em `instance/`
(pasta ignorada pelo Git), para que o sistema funcione sem configuração manual.
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"

load_dotenv(BASE_DIR / ".env")


def _segredo_persistente(env_name: str, filename: str, gerador) -> str:
    valor = os.environ.get(env_name, "").strip()
    if valor:
        return valor
    INSTANCE_DIR.mkdir(exist_ok=True)
    caminho = INSTANCE_DIR / filename
    if caminho.exists():
        return caminho.read_text(encoding="utf-8").strip()
    valor = gerador()
    caminho.write_text(valor, encoding="utf-8")
    return valor


def _bool(nome: str, padrao: bool = False) -> bool:
    return os.environ.get(nome, str(int(padrao))).strip().lower() in ("1", "true", "sim", "yes")


class Config:
    SECRET_KEY = _segredo_persistente("SECRET_KEY", "secret_key.txt", lambda: secrets.token_hex(32))
    # Chave que protege (criptografa) as senhas de clientes guardadas no banco.
    # ATENÇÃO: se perder esta chave, as senhas guardadas não poderão ser recuperadas.
    FERNET_KEY = _segredo_persistente("FERNET_KEY", "fernet.key", lambda: Fernet.generate_key().decode())

    DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
    DATABASE = os.environ.get("DATABASE_PATH", str(INSTANCE_DIR / "gestao.db"))

    # Sessão
    SESSION_COOKIE_NAME = "gestao_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)  # use 1 em produção (HTTPS)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_MINUTES", "30")))
    MAX_CONTENT_LENGTH = 64 * 1024

    # Perfis autorizados a revelar a senha de um cliente (separados por vírgula)
    REVEAL_ROLES = tuple(r.strip() for r in os.environ.get("REVEAL_ROLES", "admin").split(",") if r.strip())

    # Bloqueio de força bruta no login
    LOGIN_MAX_TENTATIVAS = int(os.environ.get("LOGIN_MAX_TENTATIVAS", "5"))
    LOGIN_JANELA_MIN = int(os.environ.get("LOGIN_JANELA_MIN", "15"))

    # Administrador inicial (criado apenas se não houver nenhum usuário)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

    DEBUG = _bool("FLASK_DEBUG", False)
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5000"))
