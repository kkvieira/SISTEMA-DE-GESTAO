"""Regras de negócio: configurações, status, arquivamento e alertas."""
from datetime import date, datetime, timezone

from db import STATUS, TIPOS
from security import agora_iso, ip_cliente
from validators import formata_cnpj, formata_cpf


# ---------- Configurações ----------
def obter_config(db) -> dict:
    cfg = {r["chave"]: int(r["valor"]) for r in db.execute("SELECT chave, valor FROM configuracoes")}
    return cfg


def salvar_config(db, valores: dict):
    for chave, valor in valores.items():
        db.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
                   "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, str(valor)))
    db.commit()


# ---------- Utilitários ----------
def parse_iso(valor: str) -> datetime:
    return datetime.strptime(valor, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def prazo_vencido(prazo) -> bool:
    return bool(prazo) and date.fromisoformat(prazo) < date.today()


def dias_de_atraso(prazo) -> int:
    return (date.today() - date.fromisoformat(prazo)).days if prazo_vencido(prazo) else 0


def registrar_historico(db, processo_id: int, usuario: str, texto: str, quando: str = None):
    db.execute("INSERT INTO atualizacoes (processo_id, usuario, texto, criado_em) VALUES (?, ?, ?, ?)",
               (processo_id, usuario, texto, quando or agora_iso()))


def auditar(db, usuario: str, acao: str, processo_id=None, detalhe=None):
    db.execute("INSERT INTO auditoria (usuario, acao, processo_id, detalhe, ip, criado_em) VALUES (?,?,?,?,?,?)",
               (usuario, acao, processo_id, detalhe, ip_cliente(), agora_iso()))


def serializar(row, detalhado=False) -> dict:
    """Converte a linha do banco em dict. NUNCA inclui a senha do cliente."""
    d = {
        "id": row["id"],
        "cliente_nome": row["cliente_nome"],
        "plano": row["plano"],
        "protocolo": row["protocolo"],
        "tipo": row["tipo"],
        "tipo_label": TIPOS[row["tipo"]]["label"],
        "status": row["status"],
        "status_label": STATUS[row["status"]],
        "prazo_resolucao": row["prazo_resolucao"],
        "criado_em": row["criado_em"],
        "atualizado_em": row["atualizado_em"],
        "concluido_em": row["concluido_em"],
    }
    if detalhado:
        d.update({
            "cpf": formata_cpf(row["cpf"]) if row["cpf"] else "",
            "cnpj": formata_cnpj(row["cnpj"]) if row["cnpj"] else "",
            "login_cliente": row["login_cliente"] or "",
            "tem_senha": bool(row["senha_cliente_enc"]),
            "prazo_vencido": prazo_vencido(row["prazo_resolucao"]) if row["status"] != "concluido" else False,
        })
    return d


# ---------- Regras de status ----------
def sincronizar_atrasos(db):
    """Marca como 'Atrasado' os processos em andamento cujo prazo de resolução venceu.

    Não altera `atualizado_em`: é uma mudança automática, não uma movimentação humana.
    """
    hoje = date.today().isoformat()
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM processos WHERE status = 'andamento' AND prazo_resolucao IS NOT NULL "
        "AND prazo_resolucao < ?", (hoje,))]
    if not ids:
        return
    agora = agora_iso()
    for pid in ids:
        db.execute("UPDATE processos SET status = 'atrasado' WHERE id = ?", (pid,))
        registrar_historico(db, pid, "sistema", "Status alterado automaticamente para Atrasado (prazo de resolução vencido).", agora)
    db.commit()


def aplicar_status(db, proc, novo: str, usuario: str):
    """Aplica a mudança de status e devolve (campos_sql, params, texto_historico).

    A confirmação da conclusão deve ser checada por quem chama.
    """
    agora = agora_iso()
    if novo == "concluido":
        return ("status = 'concluido', concluido_em = ?", [agora],
                f"Processo concluído e arquivado por {usuario}.")
    return ("status = ?, concluido_em = NULL", [novo],
            f"Status alterado de {STATUS[proc['status']]} para {STATUS[novo]}.")


# ---------- Alertas ----------
NIVEIS = {
    "alta": {"ordem": 0, "cor": "vermelho", "rotulo": "Prioridade alta"},
    "atrasado": {"ordem": 1, "cor": "vermelho", "rotulo": "Atrasado"},
    "alerta": {"ordem": 2, "cor": "amarelo", "rotulo": "Alerta"},
    "atencao": {"ordem": 3, "cor": "amarelo", "rotulo": "Atenção"},
}


def calcular_alertas(db) -> dict:
    """Calcula os alertas a partir dos dados reais (processos não concluídos).

    Tempo parado (sem atualização) e prazo de resolução são tratados separadamente:
    um processo antigo, mas movimentado e dentro do prazo, não é considerado atrasado.
    """
    cfg = obter_config(db)
    agora = datetime.now(timezone.utc)
    itens, sem_prazo = [], 0
    for r in db.execute("SELECT * FROM processos WHERE status != 'concluido'"):
        parado = (agora - parse_iso(r["atualizado_em"])).days
        atraso = dias_de_atraso(r["prazo_resolucao"])
        if not r["prazo_resolucao"]:
            sem_prazo += 1
        atrasado = r["status"] == "atrasado" or atraso > 0

        motivos = []
        if atrasado:
            nivel = "alta" if (atraso >= cfg["dias_prioridade_alta"] or parado >= cfg["dias_alerta"]) else "atrasado"
            motivos.append(f"Prazo vencido há {atraso} dia(s)" if atraso else "Marcado como atrasado")
            if parado >= cfg["dias_atencao"]:
                motivos.append(f"sem atualização há {parado} dia(s)")
        elif parado >= cfg["dias_alerta"]:
            nivel = "alerta"
            motivos.append(f"Sem atualização há {parado} dias")
        elif parado >= cfg["dias_atencao"]:
            nivel = "atencao"
            motivos.append(f"Sem atualização há {parado} dias")
        else:
            continue

        item = serializar(r)
        item.update({"nivel": nivel, "nivel_label": NIVEIS[nivel]["rotulo"], "cor": NIVEIS[nivel]["cor"],
                     "dias_sem_atualizacao": parado, "dias_atraso": atraso,
                     "motivo": "; ".join(motivos)})
        itens.append(item)

    itens.sort(key=lambda i: (NIVEIS[i["nivel"]]["ordem"], -i["dias_atraso"], -i["dias_sem_atualizacao"]))
    return {
        "itens": itens,
        "total": len(itens),
        "vermelhos": sum(1 for i in itens if i["cor"] == "vermelho"),
        "amarelos": sum(1 for i in itens if i["cor"] == "amarelo"),
        "sem_prazo": sem_prazo,
    }


def resumo(db) -> dict:
    por_tipo = {k: 0 for k in TIPOS}
    andamento = atrasados = 0
    for r in db.execute("SELECT tipo, status, COUNT(*) AS n FROM processos WHERE status != 'concluido' "
                        "GROUP BY tipo, status"):
        por_tipo[r["tipo"]] += r["n"]
        if r["status"] == "andamento":
            andamento += r["n"]
        else:
            atrasados += r["n"]
    concluidos = db.execute("SELECT COUNT(*) FROM processos WHERE status = 'concluido'").fetchone()[0]
    return {"ativos": andamento + atrasados, "andamento": andamento, "atrasados": atrasados,
            "por_tipo": por_tipo, "concluidos": concluidos}
