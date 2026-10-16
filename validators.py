"""Validação e formatação de dados (executada sempre no backend)."""
import re
from datetime import date

from db import STATUS, TIPOS

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PROTOCOLO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_\-]{2,39}$")


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def valida_cpf(valor) -> bool:
    cpf = so_digitos(valor)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[n]) * (i + 1 - n) for n in range(i))
        if int(cpf[i]) != (soma * 10 % 11) % 10:
            return False
    return True


def valida_cnpj(valor) -> bool:
    cnpj = so_digitos(valor)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    for i in (12, 13):
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-i:] if i == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(cnpj[n]) * pesos[n] for n in range(i))
        dig = 0 if soma % 11 < 2 else 11 - soma % 11
        if int(cnpj[i]) != dig:
            return False
    return True


def formata_cpf(d) -> str:
    d = so_digitos(d)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else d


def formata_cnpj(d) -> str:
    d = so_digitos(d)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def _texto(valor, maximo=200) -> str:
    return _CTRL.sub("", str(valor if valor is not None else "")).strip()[:maximo + 1]


def validar_processo(dados: dict, criando: bool):
    """Retorna (dados_limpos, erros). `erros` é um dict campo -> mensagem."""
    erros, out = {}, {}

    nome = " ".join(_texto(dados.get("cliente_nome"), 120).split())
    if not nome:
        erros["cliente_nome"] = "Informe o nome completo do cliente."
    elif len(nome) > 120 or len(nome.split()) < 2:
        erros["cliente_nome"] = "Informe o nome completo (nome e sobrenome, até 120 caracteres)."
    out["cliente_nome"] = nome

    cpf, cnpj = so_digitos(dados.get("cpf")), so_digitos(dados.get("cnpj"))
    if not cpf and not cnpj:
        erros["cpf"] = "Informe o CPF ou o CNPJ."
        erros["cnpj"] = "Informe o CPF ou o CNPJ."
    if cpf and not valida_cpf(cpf):
        erros["cpf"] = "CPF inválido."
    if cnpj and not valida_cnpj(cnpj):
        erros["cnpj"] = "CNPJ inválido."
    out["cpf"], out["cnpj"] = cpf or None, cnpj or None

    plano = " ".join(_texto(dados.get("plano"), 100).split())
    if not plano:
        erros["plano"] = "Informe o nome do plano de saúde."
    elif len(plano) > 100:
        erros["plano"] = "Nome do plano muito longo (máx. 100 caracteres)."
    out["plano"] = plano

    login = _texto(dados.get("login_cliente"), 100)
    if len(login) > 100:
        erros["login_cliente"] = "Login muito longo (máx. 100 caracteres)."
    out["login_cliente"] = login or None

    senha = str(dados.get("senha_cliente") or "")
    if len(senha) > 200:
        erros["senha_cliente"] = "Senha muito longa (máx. 200 caracteres)."
    out["senha_cliente"] = senha or None

    protocolo = _texto(dados.get("protocolo"), 40)
    if not protocolo:
        erros["protocolo"] = "Informe o número do protocolo."
    elif not _PROTOCOLO.match(protocolo):
        erros["protocolo"] = "Protocolo deve ter 3 a 40 caracteres (letras, números, ponto, barra, hífen)."
    out["protocolo"] = protocolo

    tipo = str(dados.get("tipo") or "")
    if tipo not in TIPOS:
        erros["tipo"] = "Selecione o tipo de processo."
    out["tipo"] = tipo

    status = str(dados.get("status") or "")
    if status not in STATUS:
        erros["status"] = "Selecione o status do processo."
    out["status"] = status

    prazo = str(dados.get("prazo_resolucao") or "").strip()
    if prazo:
        try:
            out["prazo_resolucao"] = date.fromisoformat(prazo).isoformat()
        except ValueError:
            erros["prazo_resolucao"] = "Data de prazo inválida."
            out["prazo_resolucao"] = None
    else:
        out["prazo_resolucao"] = None

    out["remover_senha"] = bool(dados.get("remover_senha"))
    return out, erros
