"""Conexão e esquema do banco SQLite. Todas as consultas usam parâmetros (?)."""
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
    "dias_atencao": "2",         # sem atualização há N dias -> Atenção
    "dias_alerta": "5",          # sem atualização há N dias -> Alerta
    "dias_prioridade_alta": "3",  # atrasado há N dias -> Prioridade alta
    "prazo_padrao_dias": "7",    # sugestão de prazo no cadastro
}

SCHEMA = """
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
    senha_cliente_enc TEXT,                       -- criptografada (Fernet), nunca em texto puro
    protocolo         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tipo              TEXT NOT NULL CHECK (tipo IN
        ('agendar_consulta','cancelamento','inclusao','exclusao','alteracao_cadastral')),
    status            TEXT NOT NULL DEFAULT 'andamento'
        CHECK (status IN ('andamento','atrasado','concluido')),
    prazo_resolucao   TEXT,                       -- AAAA-MM-DD (opcional)
    criado_em         TEXT NOT NULL,
    atualizado_em     TEXT NOT NULL,
    concluido_em      TEXT,                       -- preenchido ao arquivar
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

-- Trilha de auditoria (LGPD): quem acessou/alterou o quê. Sem FK para sobreviver à exclusão.
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


def normalizar(texto) -> str:
    """Minúsculas e sem acentos, para buscas que ignoram maiúsculas/acentuação."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def conectar(caminho: str) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("norm", 1, normalizar)
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    for chave, valor in CONFIG_PADRAO.items():
        conn.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, valor))
    conn.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
