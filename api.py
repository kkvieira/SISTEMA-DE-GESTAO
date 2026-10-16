"""API JSON (todas as rotas exigem usuário autenticado e token CSRF nos métodos de escrita)."""
import sqlite3

from flask import Blueprint, current_app, g, jsonify, request

import services
from db import STATUS, TIPOS, get_db, normalizar
from security import admin_required, agora_iso, criptografar, descriptografar
from validators import so_digitos, validar_processo

bp = Blueprint("api", __name__, url_prefix="/api")

LIMITE_LISTA = 500


class ApiError(Exception):
    def __init__(self, msg, status=400, campos=None, **extra):
        self.msg, self.status, self.campos, self.extra = msg, status, campos or {}, extra


@bp.errorhandler(ApiError)
def _api_error(e):
    body = {"erro": e.msg, "campos": e.campos, **e.extra}
    return jsonify(body), e.status


def _corpo() -> dict:
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        raise ApiError("Requisição inválida.", 400)
    return dados


def _usuario() -> str:
    return g.user["username"]


def _buscar(db, pid: int):
    row = db.execute("SELECT * FROM processos WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise ApiError("Processo não encontrado.", 404)
    return row


def _checar_prazo_andamento(status, prazo):
    if status == "andamento" and services.prazo_vencido(prazo):
        raise ApiError("O prazo de resolução já venceu. Ajuste o prazo ou use o status Atrasado.", 422,
                       {"prazo_resolucao": "Prazo vencido para um processo em andamento."})


def _exigir_confirmacao_conclusao(dados):
    if not dados.get("confirmar"):
        raise ApiError("Confirme a conclusão: o processo será arquivado e sairá dos alertas.", 409,
                       requer_confirmacao=True)


@bp.before_request
def _antes():
    # Regras automáticas (prazo vencido -> Atrasado) sempre refletem o banco de dados.
    if g.get("user") is not None:
        services.sincronizar_atrasos(get_db())


# ---------- Painel ----------
@bp.get("/resumo")
def resumo():
    return jsonify(services.resumo(get_db()))


@bp.get("/alertas")
def alertas():
    return jsonify(services.calcular_alertas(get_db()))


@bp.get("/configuracoes")
def ler_config():
    return jsonify(services.obter_config(get_db()))


@bp.put("/configuracoes")
@admin_required
def salvar_config():
    dados = _corpo()
    campos, valores = {}, {}
    for chave in ("dias_atencao", "dias_alerta", "dias_prioridade_alta", "prazo_padrao_dias"):
        try:
            v = int(dados.get(chave))
            if not 1 <= v <= 365:
                raise ValueError
            valores[chave] = v
        except (TypeError, ValueError):
            campos[chave] = "Informe um número de dias entre 1 e 365."
    if not campos and valores["dias_atencao"] >= valores["dias_alerta"]:
        campos["dias_atencao"] = "O prazo de Atenção deve ser menor que o de Alerta."
    if campos:
        raise ApiError("Corrija os campos destacados.", 422, campos)
    db = get_db()
    services.salvar_config(db, valores)
    services.auditar(db, _usuario(), "alterar_configuracoes", detalhe=str(valores))
    db.commit()
    return jsonify(valores)


# ---------- Processos ----------
@bp.get("/processos")
def listar():
    db = get_db()
    arquivados = request.args.get("arquivados") == "1"
    sql = "SELECT * FROM processos WHERE status " + ("= 'concluido'" if arquivados else "!= 'concluido'")
    params = []

    tipo = request.args.get("tipo", "")
    if tipo in TIPOS:
        sql += " AND tipo = ?"
        params.append(tipo)
    status = request.args.get("status", "")
    if status in ("andamento", "atrasado") and not arquivados:
        sql += " AND status = ?"
        params.append(status)

    q = request.args.get("q", "").strip()[:100]
    if q:
        def esc(s):
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc(normalizar(q))}%"
        cond = "norm(cliente_nome) LIKE ? ESCAPE '\\' OR norm(protocolo) LIKE ? ESCAPE '\\'"
        params += [like, like]
        digitos = so_digitos(q)
        if len(digitos) >= 3:
            cond += " OR cpf LIKE ? OR cnpj LIKE ?"
            params += [f"%{digitos}%", f"%{digitos}%"]
        sql += f" AND ({cond})"

    sql += " ORDER BY " + ("concluido_em DESC" if arquivados else "criado_em DESC") + " LIMIT ?"
    params.append(LIMITE_LISTA)
    return jsonify([services.serializar(r) for r in db.execute(sql, params)])


@bp.post("/processos")
def criar():
    dados = _corpo()
    limpo, erros = validar_processo(dados, criando=True)
    db = get_db()
    if not erros.get("protocolo") and db.execute(
            "SELECT 1 FROM processos WHERE protocolo = ?", (limpo["protocolo"],)).fetchone():
        erros["protocolo"] = "Já existe um processo com este número de protocolo."
    if erros:
        raise ApiError("Corrija os campos destacados.", 422, erros)
    _checar_prazo_andamento(limpo["status"], limpo["prazo_resolucao"])
    if limpo["status"] == "concluido":
        _exigir_confirmacao_conclusao(dados)

    agora = agora_iso()
    senha_enc = criptografar(limpo["senha_cliente"]) if limpo["senha_cliente"] else None
    concluido_em = agora if limpo["status"] == "concluido" else None
    try:
        cur = db.execute(
            "INSERT INTO processos (cliente_nome, cpf, cnpj, plano, login_cliente, senha_cliente_enc, protocolo, "
            "tipo, status, prazo_resolucao, criado_em, atualizado_em, concluido_em, criado_por) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (limpo["cliente_nome"], limpo["cpf"], limpo["cnpj"], limpo["plano"], limpo["login_cliente"], senha_enc,
             limpo["protocolo"], limpo["tipo"], limpo["status"], limpo["prazo_resolucao"], agora, agora,
             concluido_em, g.user["id"]))
    except sqlite3.IntegrityError:
        raise ApiError("Já existe um processo com este número de protocolo.", 422,
                       {"protocolo": "Protocolo duplicado."})
    pid = cur.lastrowid
    services.registrar_historico(db, pid, _usuario(), "Processo cadastrado.", agora)
    services.auditar(db, _usuario(), "criar", pid, limpo["protocolo"])
    db.commit()
    return jsonify(id=pid, mensagem="Processo cadastrado com sucesso!"), 201


@bp.get("/processos/<int:pid>")
def detalhe(pid):
    db = get_db()
    row = _buscar(db, pid)
    d = services.serializar(row, detalhado=True)
    d["historico"] = [dict(h) for h in db.execute(
        "SELECT usuario, texto, criado_em FROM atualizacoes WHERE processo_id = ? "
        "ORDER BY id DESC LIMIT 100", (pid,))]
    d["pode_ver_senha"] = g.user["role"] in current_app.config["REVEAL_ROLES"]
    services.auditar(db, _usuario(), "visualizar", pid)
    db.commit()
    return jsonify(d)


@bp.put("/processos/<int:pid>")
def editar(pid):
    dados = _corpo()
    db = get_db()
    atual = _buscar(db, pid)
    if atual["status"] == "concluido":
        raise ApiError("Processo concluído não pode ser editado. Reabra-o primeiro.", 409)

    limpo, erros = validar_processo(dados, criando=False)
    if not erros.get("protocolo") and db.execute(
            "SELECT 1 FROM processos WHERE protocolo = ? AND id != ?", (limpo["protocolo"], pid)).fetchone():
        erros["protocolo"] = "Já existe outro processo com este número de protocolo."
    if erros:
        raise ApiError("Corrija os campos destacados.", 422, erros)
    _checar_prazo_andamento(limpo["status"], limpo["prazo_resolucao"])
    if limpo["status"] == "concluido":
        _exigir_confirmacao_conclusao(dados)

    agora = agora_iso()
    sets = ["cliente_nome = ?", "cpf = ?", "cnpj = ?", "plano = ?", "login_cliente = ?", "protocolo = ?",
            "tipo = ?", "prazo_resolucao = ?", "atualizado_em = ?"]
    params = [limpo["cliente_nome"], limpo["cpf"], limpo["cnpj"], limpo["plano"], limpo["login_cliente"],
              limpo["protocolo"], limpo["tipo"], limpo["prazo_resolucao"], agora]
    if limpo["senha_cliente"]:                       # em branco = manter a senha atual
        sets.append("senha_cliente_enc = ?")
        params.append(criptografar(limpo["senha_cliente"]))
    elif limpo["remover_senha"]:
        sets.append("senha_cliente_enc = NULL")

    notas = ["Dados do processo editados."]
    if limpo["status"] != atual["status"]:
        campo, extra, texto = services.aplicar_status(db, atual, limpo["status"], _usuario())
        sets.append(campo)
        params += extra
        notas.append(texto)
    try:
        db.execute(f"UPDATE processos SET {', '.join(sets)} WHERE id = ?", params + [pid])
    except sqlite3.IntegrityError:
        raise ApiError("Protocolo duplicado.", 422, {"protocolo": "Protocolo duplicado."})
    services.registrar_historico(db, pid, _usuario(), " ".join(notas), agora)
    services.auditar(db, _usuario(), "editar", pid, limpo["protocolo"])
    db.commit()
    return jsonify(id=pid, mensagem="Processo atualizado com sucesso!")


@bp.patch("/processos/<int:pid>/status")
def alterar_status(pid):
    dados = _corpo()
    novo = str(dados.get("status") or "")
    if novo not in STATUS:
        raise ApiError("Status inválido.", 422, {"status": "Status inválido."})
    db = get_db()
    atual = _buscar(db, pid)
    if atual["status"] == "concluido":
        raise ApiError("Processo concluído. Reabra-o para alterar o status.", 409)
    if novo == atual["status"]:
        return jsonify(id=pid, mensagem="O status já é este.")
    _checar_prazo_andamento(novo, atual["prazo_resolucao"])
    if novo == "concluido":
        _exigir_confirmacao_conclusao(dados)

    campo, extra, texto = services.aplicar_status(db, atual, novo, _usuario())
    agora = agora_iso()
    db.execute(f"UPDATE processos SET {campo}, atualizado_em = ? WHERE id = ?", extra + [agora, pid])
    services.registrar_historico(db, pid, _usuario(), texto, agora)
    services.auditar(db, _usuario(), "status", pid, f"{atual['status']} -> {novo}")
    db.commit()
    msg = "Processo concluído e arquivado." if novo == "concluido" else "Status atualizado."
    return jsonify(id=pid, mensagem=msg)


@bp.post("/processos/<int:pid>/atualizacoes")
def nova_atualizacao(pid):
    texto = " ".join(str(_corpo().get("texto") or "").split())
    if not texto:
        raise ApiError("Escreva a atualização antes de salvar.", 422, {"texto": "Campo obrigatório."})
    if len(texto) > 1000:
        raise ApiError("Texto muito longo (máx. 1000 caracteres).", 422, {"texto": "Máx. 1000 caracteres."})
    db = get_db()
    if _buscar(db, pid)["status"] == "concluido":
        raise ApiError("Processo concluído. Reabra-o para registrar atualizações.", 409)
    agora = agora_iso()
    services.registrar_historico(db, pid, _usuario(), texto, agora)
    db.execute("UPDATE processos SET atualizado_em = ? WHERE id = ?", (agora, pid))
    services.auditar(db, _usuario(), "atualizacao", pid)
    db.commit()
    return jsonify(id=pid, mensagem="Atualização registrada."), 201


@bp.post("/processos/<int:pid>/senha")
def revelar_senha(pid):
    if g.user["role"] not in current_app.config["REVEAL_ROLES"]:
        raise ApiError("Você não tem permissão para visualizar senhas de clientes.", 403)
    db = get_db()
    row = _buscar(db, pid)
    if not row["senha_cliente_enc"]:
        raise ApiError("Nenhuma senha armazenada para este processo.", 404)
    senha = descriptografar(row["senha_cliente_enc"])
    if senha is None:
        raise ApiError("Não foi possível descriptografar a senha (chave inválida).", 500)
    services.auditar(db, _usuario(), "revelar_senha", pid)
    db.commit()
    return jsonify(senha=senha)


@bp.post("/processos/<int:pid>/reabrir")
def reabrir(pid):
    db = get_db()
    row = _buscar(db, pid)
    if row["status"] != "concluido":
        raise ApiError("O processo não está concluído.", 409)
    novo = "atrasado" if services.prazo_vencido(row["prazo_resolucao"]) else "andamento"
    agora = agora_iso()
    db.execute("UPDATE processos SET status = ?, concluido_em = NULL, atualizado_em = ? WHERE id = ?",
               (novo, agora, pid))
    services.registrar_historico(db, pid, _usuario(), f"Processo reaberto (status: {STATUS[novo]}).", agora)
    services.auditar(db, _usuario(), "reabrir", pid)
    db.commit()
    return jsonify(id=pid, mensagem="Processo reaberto e devolvido à sua pasta.")


@bp.delete("/processos/<int:pid>")
def excluir(pid):
    dados = request.get_json(silent=True) or {}
    db = get_db()
    row = _buscar(db, pid)
    if row["status"] == "concluido":
        # Exclusão definitiva de arquivados: somente admin e com digitação do protocolo.
        if g.user["role"] != "admin":
            raise ApiError("Apenas administradores podem excluir definitivamente processos arquivados.", 403)
        if str(dados.get("confirmacao", "")).strip().lower() != row["protocolo"].lower():
            raise ApiError("Digite o número do protocolo para confirmar a exclusão definitiva.", 422)
    elif dados.get("confirmar") is not True:
        raise ApiError("Confirmação obrigatória para excluir.", 422)
    db.execute("DELETE FROM processos WHERE id = ?", (pid,))
    services.auditar(db, _usuario(), "excluir", pid, row["protocolo"])
    db.commit()
    return jsonify(mensagem="Processo excluído definitivamente.")
