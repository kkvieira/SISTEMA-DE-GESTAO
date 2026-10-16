"""Ponto de entrada: fábrica da aplicação Flask, login/logout, páginas e cabeçalhos de segurança.

Execute com:  python app.py
"""
import secrets
import sys

import click
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db as database
import services
from api import bp as api_bp
from config import INSTANCE_DIR, Config
from security import (agora_iso, csrf_token, csrf_valido, limpar_falhas_login, login_bloqueado,
                      login_required, registrar_falha_login)

# Hash falso para igualar o tempo de resposta quando o usuário não existe.
_HASH_FALSO = generate_password_hash("senha-inexistente")
SENHA_MIN = 10


def criar_usuario(conn, username: str, senha: str, role: str = "operador"):
    if len(senha) < SENHA_MIN:
        raise ValueError(f"A senha deve ter pelo menos {SENHA_MIN} caracteres.")
    conn.execute("INSERT INTO usuarios (username, password_hash, role, criado_em) VALUES (?,?,?,?)",
                 (username.strip(), generate_password_hash(senha), role, agora_iso()))
    conn.commit()


def _bootstrap_admin(app):
    """Cria ou atualiza a senha do primeiro administrador a partir de ADMIN_PASSWORD."""
    with app.app_context():
        conn = database.get_db()
        senha = app.config.get("ADMIN_PASSWORD", "").strip()
        user_row = conn.execute("SELECT id, username FROM usuarios WHERE role = 'admin' LIMIT 1").fetchone()
        
        if user_row:
            if senha:
                # Se o usuário configurou uma senha na Vercel/env, atualiza a senha do admin
                conn.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?", (generate_password_hash(senha), user_row["id"]))
                conn.commit()
            return

        gerada = not senha
        if gerada:
            senha = secrets.token_urlsafe(12)
        criar_usuario(conn, app.config["ADMIN_USERNAME"], senha, "admin")
        if gerada:
            print("\n" + "=" * 62)
            print(" PRIMEIRO ACESSO - guarde estas credenciais (exibidas só uma vez)")
            print(f"   usuário: {app.config['ADMIN_USERNAME']}")
            print(f"   senha  : {senha}")
            print("=" * 62 + "\n", flush=True)


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(INSTANCE_DIR))
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    database.init_app(app)
    _bootstrap_admin(app)
    app.register_blueprint(api_bp)

    # ---------- Sessão, autenticação e CSRF ----------
    @app.before_request
    def _carregar_usuario():
        g.user = None
        uid = session.get("uid")
        if uid:
            row = database.get_db().execute(
                "SELECT id, username, role FROM usuarios WHERE id = ? AND ativo = 1", (uid,)).fetchone()
            if row:
                g.user = row
                session.permanent = True  # renova o prazo de inatividade
            else:
                session.clear()
        if request.path.startswith("/api/") and g.user is None:
            return jsonify(erro="Sessão expirada. Entre novamente."), 401
        if request.method not in ("GET", "HEAD", "OPTIONS") and not csrf_valido():
            if request.path.startswith("/api/"):
                return jsonify(erro="Token de segurança inválido. Recarregue a página."), 400
            return render_template("login.html", erro="Sessão de segurança expirada. Tente novamente."), 400

    @app.after_request
    def _cabecalhos(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if request.path.startswith("/api/") or request.endpoint in ("index", "concluidos", "login"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def _contexto():
        return {"csrf_token": csrf_token, "usuario": g.get("user"),
                "TIPOS": database.TIPOS, "STATUS": database.STATUS}

    # ---------- Autenticação ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("login.html")

        conn = database.get_db()
        username = request.form.get("username", "").strip()[:80]
        senha = request.form.get("password", "")[:200]
        if login_bloqueado(conn, username):
            return render_template("login.html", erro="Muitas tentativas. Aguarde alguns minutos e tente novamente."), 429
        row = conn.execute("SELECT * FROM usuarios WHERE username = ? AND ativo = 1", (username,)).fetchone()
        ok = check_password_hash(row["password_hash"] if row else _HASH_FALSO, senha)
        if not (row and ok):
            registrar_falha_login(conn, username)
            services.auditar(conn, username or "?", "login_falhou")
            conn.commit()
            return render_template("login.html", erro="Usuário ou senha incorretos.", username=username), 401

        limpar_falhas_login(conn, username)
        session.clear()               # evita fixação de sessão
        session["uid"] = row["id"]
        session.permanent = True
        csrf_token()
        services.auditar(conn, row["username"], "login")
        conn.commit()
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        if g.user:
            services.auditar(database.get_db(), g.user["username"], "logout")
            database.get_db().commit()
        session.clear()
        return redirect(url_for("login"))

    # ---------- Páginas ----------
    @app.get("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.get("/concluidos")
    @login_required
    def concluidos():
        return render_template("concluidos.html")

    # ---------- Erros ----------
    @app.errorhandler(404)
    def _404(_e):
        if request.path.startswith("/api/"):
            return jsonify(erro="Recurso não encontrado."), 404
        return redirect(url_for("index"))

    @app.errorhandler(405)
    def _405(_e):
        return jsonify(erro="Método não permitido."), 405

    @app.errorhandler(413)
    def _413(_e):
        return jsonify(erro="Requisição muito grande."), 413

    @app.errorhandler(500)
    def _500(_e):
        if request.path.startswith("/api/"):
            return jsonify(erro="Erro interno. Tente novamente."), 500
        return "Erro interno do servidor.", 500

    # ---------- Comandos CLI ----------
    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice(["admin", "operador"]), default="operador")
    @click.password_option(confirmation_prompt=True)
    def _cli_create_user(username, role, password):
        """Cria um usuário autorizado: flask --app app create-user NOME --role operador"""
        try:
            criar_usuario(database.get_db(), username, password, role)
            click.echo(f"Usuário '{username}' criado ({role}).")
        except Exception as exc:  # usuário duplicado, senha curta etc.
            click.echo(f"Erro: {exc}")
            sys.exit(1)

    return app


# Instância da aplicação WSGI (necessária para Vercel Serverless / Gunicorn)
app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)

