"""Testes dos principais fluxos. Execute:  python -m unittest -v"""
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from app import create_app, criar_usuario
import db as database


def cpf_teste(base: str) -> str:
    """Gera CPF algoritmicamente válido a partir de 9 dígitos (apenas para testes)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        s = sum(v * (n + 1 - i) for i, v in enumerate(d))
        d.append((s * 10 % 11) % 10)
    return "".join(map(str, d))


def cnpj_teste(base: str) -> str:
    d = [int(c) for c in base]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        s = sum(v * p for v, p in zip(d, pesos))
        d.append(0 if s % 11 < 2 else 11 - s % 11)
    return "".join(map(str, d))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class BaseTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.path, "ADMIN_USERNAME": "admin",
                               "ADMIN_PASSWORD": "senha-de-teste-123", "SESSION_COOKIE_SECURE": False})
        with self.app.app_context():
            criar_usuario(database.get_db(), "operador", "outra-senha-1234", "operador")
        self.c = self.app.test_client()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    # helpers
    def token(self, client=None):
        client = client or self.c
        html = client.get("/login").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def login(self, user="admin", pw="senha-de-teste-123", client=None):
        client = client or self.c
        tk = self.token(client)
        r = client.post("/login", data={"username": user, "password": pw, "csrf_token": tk})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:200])
        return self.token_from_page(client)

    def token_from_page(self, client):
        html = client.get("/").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def api(self, method, url, tk, body=None, client=None):
        client = client or self.c
        return getattr(client, method)(url, json=body, headers={"X-CSRF-Token": tk})

    def payload(self, **kw):
        base = {"cliente_nome": "Maria da Silva", "cpf": cpf_teste("123456789"), "cnpj": "", "plano": "Plano Ouro",
                "login_cliente": "maria.s", "senha_cliente": "SegredoDoCliente!9", "protocolo": "PROTO-001",
                "tipo": "inclusao", "status": "andamento",
                "prazo_resolucao": (date.today() + timedelta(days=5)).isoformat()}
        base.update(kw)
        return base

    def criar(self, tk, **kw):
        r = self.api("post", "/api/processos", tk, self.payload(**kw))
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def sql(self, q, params=()):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(q, params).fetchall()
        conn.commit()
        conn.close()
        return rows


class SegurancaTest(BaseTest):
    def test_rotas_protegidas(self):
        self.assertEqual(self.c.get("/api/resumo").status_code, 401)
        self.assertEqual(self.c.get("/api/processos").status_code, 401)
        r = self.c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_login_invalido_e_csrf(self):
        tk = self.token()
        r = self.c.post("/login", data={"username": "admin", "password": "errada", "csrf_token": tk})
        self.assertEqual(r.status_code, 401)
        r = self.c.post("/login", data={"username": "admin", "password": "senha-de-teste-123"})
        self.assertEqual(r.status_code, 400)  # sem CSRF

    def test_csrf_na_api(self):
        tk = self.login()
        r = self.c.post("/api/processos", json=self.payload())  # sem header
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api("post", "/api/processos", tk, self.payload()).status_code, 201)

    def test_bloqueio_forca_bruta(self):
        for _ in range(5):
            tk = self.token()
            self.c.post("/login", data={"username": "admin", "password": "x", "csrf_token": tk})
        tk = self.token()
        r = self.c.post("/login", data={"username": "admin", "password": "senha-de-teste-123", "csrf_token": tk})
        self.assertEqual(r.status_code, 429)

    def test_cabecalhos(self):
        r = self.c.get("/login")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        cookie = r.headers["Set-Cookie"].lower()  # primeira resposta define a sessão
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_senha_cliente_criptografada_e_oculta(self):
        tk = self.login()
        pid = self.criar(tk)
        bruto = self.sql("SELECT senha_cliente_enc FROM processos WHERE id=?", (pid,))[0][0]
        self.assertNotIn("SegredoDoCliente", bruto)
        for url in ("/api/processos", f"/api/processos/{pid}"):
            self.assertNotIn("SegredoDoCliente", self.c.get(url).get_data(as_text=True))
        r = self.api("post", f"/api/processos/{pid}/senha", tk, {})
        self.assertEqual(r.get_json()["senha"], "SegredoDoCliente!9")
        # operador não está autorizado
        c2 = self.app.test_client()
        tk2 = self.login("operador", "outra-senha-1234", client=c2)
        self.assertEqual(self.api("post", f"/api/processos/{pid}/senha", tk2, {}, client=c2).status_code, 403)
        self.assertEqual(self.api("put", "/api/configuracoes", tk2, {}, client=c2).status_code, 403)
        acoes = [r[0] for r in self.sql("SELECT acao FROM auditoria")]
        self.assertIn("revelar_senha", acoes)

    def test_sql_injection_na_busca(self):
        tk = self.login()
        self.criar(tk)
        r = self.c.get("/api/processos?q=' OR 1=1 --")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])
        self.assertEqual(len(self.c.get("/api/processos?q=%25").get_json()), 0)  # % é literal


class ProcessosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.tk = self.login()

    def test_validacoes(self):
        r = self.api("post", "/api/processos", self.tk, self.payload(cpf="111.111.111-11"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("cpf", r.get_json()["campos"])
        r = self.api("post", "/api/processos", self.tk, self.payload(cpf="", cnpj=""))
        self.assertEqual(r.status_code, 422)
        r = self.api("post", "/api/processos", self.tk, self.payload(cliente_nome="Maria", tipo="x"))
        self.assertEqual(set(r.get_json()["campos"]) >= {"cliente_nome", "tipo"}, True)
        r = self.api("post", "/api/processos", self.tk,
                     self.payload(cpf="", cnpj=cnpj_teste("112223330001"), protocolo="CNPJ-1"))
        self.assertEqual(r.status_code, 201)
        r = self.api("post", "/api/processos", self.tk,
                     self.payload(prazo_resolucao="2000-01-01", protocolo="X-PASSADO"))
        self.assertEqual(r.status_code, 422)  # andamento com prazo vencido

    def test_protocolo_duplicado(self):
        self.criar(self.tk)
        r = self.api("post", "/api/processos", self.tk, self.payload(cliente_nome="Outro Cliente"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("protocolo", r.get_json()["campos"])

    def test_listar_buscar_filtrar_e_contagens(self):
        a = self.criar(self.tk, cliente_nome="João Ávila Souza", protocolo="A-100", tipo="inclusao")
        self.criar(self.tk, cliente_nome="Ana Paula Lima", protocolo="B-200", tipo="exclusao",
                   cpf=cpf_teste("987654321"))
        self.assertEqual(len(self.c.get("/api/processos?tipo=inclusao").get_json()), 1)
        self.assertEqual(self.c.get("/api/processos?q=joao avila").get_json()[0]["id"], a)  # sem acento
        self.assertEqual(len(self.c.get("/api/processos?q=b-200").get_json()), 1)
        cpf = cpf_teste("987654321")
        fmt = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        self.assertEqual(len(self.c.get(f"/api/processos?q={fmt}").get_json()), 1)
        res = self.c.get("/api/resumo").get_json()
        self.assertEqual((res["ativos"], res["por_tipo"]["inclusao"], res["por_tipo"]["exclusao"]), (2, 1, 1))
        d = self.c.get(f"/api/processos/{a}").get_json()
        self.assertEqual(d["cpf"].count("."), 2)  # formatado
        self.assertTrue(d["criado_em"] and d["atualizado_em"])

    def test_editar_e_manter_senha(self):
        pid = self.criar(self.tk)
        r = self.api("put", f"/api/processos/{pid}", self.tk,
                     self.payload(plano="Plano Prata", senha_cliente=""))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.api("post", f"/api/processos/{pid}/senha", self.tk, {}).get_json()["senha"],
                         "SegredoDoCliente!9")
        self.assertEqual(self.c.get(f"/api/processos/{pid}").get_json()["plano"], "Plano Prata")
        self.api("put", f"/api/processos/{pid}", self.tk, self.payload(remover_senha=True, senha_cliente=""))
        self.assertEqual(self.api("post", f"/api/processos/{pid}/senha", self.tk, {}).status_code, 404)

    def test_conclusao_e_arquivamento(self):
        pid = self.criar(self.tk)
        # sem confirmação -> recusado
        r = self.api("patch", f"/api/processos/{pid}/status", self.tk, {"status": "concluido"})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()["requer_confirmacao"])
        r = self.api("patch", f"/api/processos/{pid}/status", self.tk, {"status": "concluido", "confirmar": True})
        self.assertEqual(r.status_code, 200)
        # sai das listas, contagens e alertas; permanece no banco
        self.assertEqual(self.c.get("/api/processos").get_json(), [])
        self.assertEqual(self.c.get("/api/resumo").get_json()["ativos"], 0)
        self.assertEqual(self.c.get("/api/resumo").get_json()["concluidos"], 1)
        self.assertEqual(self.c.get("/api/alertas").get_json()["total"], 0)
        arq = self.c.get("/api/processos?arquivados=1").get_json()
        self.assertEqual(len(arq), 1)
        self.assertTrue(arq[0]["concluido_em"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM processos")[0][0], 1)
        # não edita arquivado; reabre
        self.assertEqual(self.api("put", f"/api/processos/{pid}", self.tk, self.payload()).status_code, 409)
        self.assertEqual(self.api("post", f"/api/processos/{pid}/reabrir", self.tk, {}).status_code, 200)
        self.assertEqual(self.c.get("/api/resumo").get_json()["ativos"], 1)

    def test_alertas_parado_vs_atrasado(self):
        agora = datetime.now(timezone.utc)
        p_novo = self.criar(self.tk, protocolo="N-1")
        p2 = self.criar(self.tk, protocolo="N-2")
        p6 = self.criar(self.tk, protocolo="N-6")
        p_atr = self.criar(self.tk, protocolo="N-ATR")
        p_velho = self.criar(self.tk, protocolo="N-VELHO", prazo_resolucao=(date.today() + timedelta(days=30)).isoformat())
        ontem3 = (date.today() - timedelta(days=4)).isoformat()
        self.sql("UPDATE processos SET atualizado_em=? WHERE id=?", (iso(agora - timedelta(days=2, hours=1)), p2))
        self.sql("UPDATE processos SET atualizado_em=? WHERE id=?", (iso(agora - timedelta(days=6)), p6))
        self.sql("UPDATE processos SET prazo_resolucao=? WHERE id=?", (ontem3, p_atr))
        # antigo (criado há 60 dias), mas atualizado agora e dentro do prazo -> NÃO é alerta
        self.sql("UPDATE processos SET criado_em=? WHERE id=?", (iso(agora - timedelta(days=60)), p_velho))

        al = self.c.get("/api/alertas").get_json()
        por_id = {i["id"]: i for i in al["itens"]}
        self.assertNotIn(p_novo, por_id)
        self.assertNotIn(p_velho, por_id)
        self.assertEqual(por_id[p2]["nivel"], "atencao")
        self.assertEqual(por_id[p2]["cor"], "amarelo")
        self.assertEqual(por_id[p6]["nivel"], "alerta")
        self.assertEqual(por_id[p_atr]["nivel"], "alta")  # atrasado há 4 dias (>= 3)
        self.assertEqual(por_id[p_atr]["cor"], "vermelho")
        self.assertEqual(al["itens"][0]["id"], p_atr)  # mais crítico primeiro
        # sincronização automática refletida no status/resumo
        self.assertEqual(self.c.get(f"/api/processos/{p_atr}").get_json()["status"], "atrasado")
        self.assertEqual(self.c.get("/api/resumo").get_json()["atrasados"], 1)

    def test_atualizacao_zera_alerta_parado(self):
        agora = datetime.now(timezone.utc)
        pid = self.criar(self.tk)
        self.sql("UPDATE processos SET atualizado_em=? WHERE id=?", (iso(agora - timedelta(days=6)), pid))
        self.assertEqual(self.c.get("/api/alertas").get_json()["total"], 1)
        r = self.api("post", f"/api/processos/{pid}/atualizacoes", self.tk, {"texto": "Aguardando operadora"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get("/api/alertas").get_json()["total"], 0)

    def test_status_manual_atrasado_gera_alerta(self):
        pid = self.criar(self.tk)
        self.api("patch", f"/api/processos/{pid}/status", self.tk, {"status": "atrasado"})
        al = self.c.get("/api/alertas").get_json()
        self.assertEqual(al["total"], 1)
        self.assertEqual(al["itens"][0]["cor"], "vermelho")

    def test_configuracao_de_prazos(self):
        agora = datetime.now(timezone.utc)
        pid = self.criar(self.tk)
        self.sql("UPDATE processos SET atualizado_em=? WHERE id=?", (iso(agora - timedelta(days=1, hours=2)), pid))
        self.assertEqual(self.c.get("/api/alertas").get_json()["total"], 0)
        r = self.api("put", "/api/configuracoes", self.tk,
                     {"dias_atencao": 1, "dias_alerta": 3, "dias_prioridade_alta": 2, "prazo_padrao_dias": 7})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/alertas").get_json()["total"], 1)
        r = self.api("put", "/api/configuracoes", self.tk,
                     {"dias_atencao": 5, "dias_alerta": 3, "dias_prioridade_alta": 2, "prazo_padrao_dias": 7})
        self.assertEqual(r.status_code, 422)

    def test_exclusao(self):
        pid = self.criar(self.tk)
        self.assertEqual(self.api("delete", f"/api/processos/{pid}", self.tk, {}).status_code, 422)
        self.assertEqual(self.api("delete", f"/api/processos/{pid}", self.tk, {"confirmar": True}).status_code, 200)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM processos")[0][0], 0)
        # arquivado exige digitar o protocolo
        pid = self.criar(self.tk, protocolo="ARQ-9")
        self.api("patch", f"/api/processos/{pid}/status", self.tk, {"status": "concluido", "confirmar": True})
        self.assertEqual(self.api("delete", f"/api/processos/{pid}", self.tk, {"confirmar": True}).status_code, 422)
        self.assertEqual(self.api("delete", f"/api/processos/{pid}", self.tk, {"confirmacao": "ARQ-9"}).status_code, 200)

    def test_persistencia_entre_reinicios(self):
        self.criar(self.tk)
        app2 = create_app({"TESTING": True, "DATABASE": self.path, "ADMIN_PASSWORD": "senha-de-teste-123"})
        c2 = app2.test_client()
        tk = self.login(client=c2)
        self.assertEqual(len(c2.get("/api/processos").get_json()), 1)

    def test_paginas(self):
        self.assertIn("Sala de arquivos", self.c.get("/").get_data(as_text=True))
        self.assertEqual(self.c.get("/concluidos").status_code, 200)


if __name__ == "__main__":
    unittest.main()
