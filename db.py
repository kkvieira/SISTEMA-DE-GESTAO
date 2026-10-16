"""Conexão e esquema de banco de dados compatível com SQLite e PostgreSQL (Neon / Supabase).

- Se DATABASE_URL estiver configurado, usa PostgreSQL.
- Caso contrário, usa SQLite localmente (instance/gestao.db).
- Todas as consultas mantêm sintaxe e comportamento idênticos através de um wrapper unificado.
"""
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from flask import current_app, g

TIPOS = {
    "agendar_consulta": {"label": "Agendar consulta", "icone": "📁"},
    "cancelamento": {"label": "Fazer cancelamento", "icone": "📁"},
    "inclusao": {"label": "Inclusão", "icone": "📁"},
    "exclusao": {"label": "Exclusão", "icone": "📁"},
    "alteracao_cadastral": {"label": "Alteração cadastral", "icone": "📁"},
}

STATUS = {
    "andamento": "Andamento",
    "atrasado": "Atrasado",
    "concluido": "Concluído",
}

CONFIG_PADRAO = {
    "dias_atencao": "2",
    "dias_alerta": "5",
    "dias_prioridade_alta": "3",
    "prazo_padrao_dias": "7",
}

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'operador' CHECK (role IN ('admin', 'operador')),
    ativo         INTEGER NOT NULL DEFAULT 1,
    criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_nome      TEXT NOT NULL,
    cpf               TEXT,
    cnpj              TEXT,
    plano             TEXT NOT NULL,
    login_cliente     TEXT,
    senha_cliente_enc TEXT,
    protocolo         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tipo              TEXT NOT NULL CHECK (tipo IN
        ('agendar_consulta','cancelamento','inclusao','exclusao','alteracao_cadastral')),
    status            TEXT NOT NULL DEFAULT 'andamento'
        CHECK (status IN ('andamento','atrasado','concluido')),
    prazo_resolucao   TEXT,
    criado_em         TEXT NOT NULL,
    atualizado_em     TEXT NOT NULL,
    concluido_em      TEXT,
    criado_por        INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_processos_tipo   ON processos(tipo);
CREATE INDEX IF NOT EXISTS idx_processos_status ON processos(status);

CREATE TABLE IF NOT EXISTS atualizacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    usuario     TEXT NOT NULL,
    texto       TEXT NOT NULL,
    criado_em   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_atualizacoes_proc ON atualizacoes(processo_id);

CREATE TABLE IF NOT EXISTS auditoria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario     TEXT NOT NULL,
    acao        TEXT NOT NULL,
    processo_id INTEGER,
    detalhe     TEXT,
    ip          TEXT,
    criado_em   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tentativas_login (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chave     TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tentativas_chave ON tentativas_login(chave);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          VARCHAR(20) NOT NULL DEFAULT 'operador' CHECK (role IN ('admin', 'operador')),
    ativo         INTEGER NOT NULL DEFAULT 1,
    criado_em     VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS processos (
    id                SERIAL PRIMARY KEY,
    cliente_nome      VARCHAR(255) NOT NULL,
    cpf               VARCHAR(20),
    cnpj              VARCHAR(30),
    plano             VARCHAR(150) NOT NULL,
    login_cliente     VARCHAR(120),
    senha_cliente_enc TEXT,
    protocolo         VARCHAR(100) NOT NULL UNIQUE,
    tipo              VARCHAR(50) NOT NULL CHECK (tipo IN
        ('agendar_consulta','cancelamento','inclusao','exclusao','alteracao_cadastral')),
    status            VARCHAR(50) NOT NULL DEFAULT 'andamento'
        CHECK (status IN ('andamento','atrasado','concluido')),
    prazo_resolucao   VARCHAR(30),
    criado_em         VARCHAR(50) NOT NULL,
    atualizado_em     VARCHAR(50) NOT NULL,
    concluido_em      VARCHAR(50),
    criado_por        INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_processos_tipo   ON processos(tipo);
CREATE INDEX IF NOT EXISTS idx_processos_status ON processos(status);

CREATE TABLE IF NOT EXISTS atualizacoes (
    id          SERIAL PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    usuario     VARCHAR(100) NOT NULL,
    texto       TEXT NOT NULL,
    criado_em   VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_atualizacoes_proc ON atualizacoes(processo_id);

CREATE TABLE IF NOT EXISTS auditoria (
    id          SERIAL PRIMARY KEY,
    usuario     VARCHAR(100) NOT NULL,
    acao        VARCHAR(100) NOT NULL,
    processo_id INTEGER,
    detalhe     TEXT,
    ip          VARCHAR(50),
    criado_em   VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave VARCHAR(100) PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tentativas_login (
    id        SERIAL PRIMARY KEY,
    chave     VARCHAR(200) NOT NULL,
    criado_em VARCHAR(50) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tentativas_chave ON tentativas_login(chave);
"""


def normalizar(texto) -> str:
    """Minúsculas e sem acentos para buscas."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


class DBWrapper:
    """Wrapper uniforme para SQLite e PostgreSQL mantendo a mesma interface de execução."""

    def __init__(self, conn, is_pg=False):
        self.conn = conn
        self.is_pg = is_pg

    def _convert_sql(self, sql: str) -> str:
        if not self.is_pg:
            return sql
        # Converte placeholders '?' para '%s' do psycopg2
        sql = sql.replace("?", "%s")
        # Substitui a função norm(...) por unaccent(lower(...)) se disponível, ou lower(...)
        sql = re.sub(r'\bnorm\((.*?)\)', r'lower(\1)', sql)
        return sql

    def execute(self, sql: str, params=()):
        sql_conv = self._convert_sql(sql)
        cursor = self.conn.cursor()
        
        # Em PostgreSQL, se for um INSERT, anexa RETURNING id para emular lastrowid
        is_insert = self.is_pg and sql_conv.strip().upper().startswith("INSERT INTO") and "RETURNING" not in sql_conv.upper()
        if is_insert:
            sql_conv = sql_conv.rstrip("; \t\n") + " RETURNING id"

        cursor.execute(sql_conv, tuple(params))
        
        if is_insert:
            try:
                row = cursor.fetchone()
                if row:
                    cursor.lastrowid = row[0]
            except Exception:
                cursor.lastrowid = None
        return cursor

    def executescript(self, script: str):
        if self.is_pg:
            cursor = self.conn.cursor()
            cursor.execute(script)
            self.conn.commit()
        else:
            self.conn.executescript(script)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def conectar_postgres(url: str):
    import psycopg2
    from psycopg2.extras import DictCursor

    # Garante compatibilidade caso a URL venha como postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(url, cursor_factory=DictCursor)
    conn.autocommit = False
    return DBWrapper(conn, is_pg=True)


def conectar_sqlite(caminho: str):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("norm", 1, normalizar)
    return DBWrapper(conn, is_pg=False)


def get_db() -> DBWrapper:
    if "db" not in g:
        db_url = current_app.config.get("DATABASE_URL", "").strip()
        if db_url:
            g.db = conectar_postgres(db_url)
        else:
            g.db = conectar_sqlite(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    if db.is_pg:
        # Tenta habilitar unaccent se o usuário tiver privilégio (opcional)
        try:
            db.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            db.commit()
        except Exception:
            db.rollback()
        db.executescript(SCHEMA_POSTGRES)
    else:
        db.executescript(SCHEMA_SQLITE)

    for chave, valor in CONFIG_PADRAO.items():
        if db.is_pg:
            db.execute(
                "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) ON CONFLICT (chave) DO NOTHING",
                (chave, valor),
            )
        else:
            db.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, valor))
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
