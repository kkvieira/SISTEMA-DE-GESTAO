# 🩺 Gestão de Tratativas de Clientes — "Sala de arquivos"

Sistema web (Flask + SQLite + HTML/CSS/JS) para controlar processos de clientes de planos de saúde, com
tema escuro, alertas automáticos de processos parados/atrasados e arquivamento de concluídos.

## Estrutura

```
SISTEMA DE GESTÃO/
├── app.py            # Fábrica Flask, login/logout, páginas, cabeçalhos de segurança, CLI
├── api.py            # API JSON (processos, alertas, status, configurações)
├── services.py       # Regras de negócio (status, arquivamento, alertas)
├── security.py       # CSRF, criptografia (Fernet), controle de acesso, anti força bruta
├── validators.py     # Validação backend (CPF/CNPJ com dígitos verificadores etc.)
├── db.py             # Esquema SQLite e conexão
├── config.py         # Configurações (.env)
├── templates/        # base, login, index, concluidos, _campos (formulário), _dialogs
├── static/css/style.css
├── static/js/        # common.js, home.js, concluidos.js
├── tests/test_app.py # Testes automatizados dos fluxos principais
├── requirements.txt · .env.example · .gitignore
└── instance/         # (criada automaticamente) banco gestao.db e chaves — fora do Git
```

## Como executar no Windows (terminal do VS Code)

Pré-requisito: **Python 3.10+** (https://www.python.org/downloads/ — marque *Add python.exe to PATH*).

Abra a pasta no VS Code, abra o terminal (``Ctrl+` ``, PowerShell) e rode:

```powershell
# 1) Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Se o PowerShell bloquear scripts: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2) Dependências
pip install -r requirements.txt

# 3) (Opcional) configurações
Copy-Item .env.example .env

# 4) Iniciar
python app.py
```

Abra **http://127.0.0.1:5000**.

**Primeiro acesso:** na 1ª execução o terminal mostra, uma única vez, o usuário `admin` e uma senha aleatória.
(Ou defina `ADMIN_USERNAME`/`ADMIN_PASSWORD` no `.env` antes de iniciar; mínimo 10 caracteres.)

Criar outros usuários:

```powershell
flask --app app create-user maria --role operador
```

Rodar os testes: `python -m unittest -v`

> Os dados ficam em `instance/gestao.db` e persistem após reiniciar. Faça backup dessa pasta
> (incluindo `fernet.key`, sem a qual as senhas guardadas não podem ser lidas).
> Evite manter o projeto em pasta sincronizada pelo OneDrive em produção (risco de corromper o SQLite).

## Funcionalidades

- Cadastro com validação (front e back), máscara e validação real de CPF/CNPJ, protocolo único.
- 5 pastas por tipo com contagem em tempo real; busca por nome (sem acento), CPF ou protocolo; filtros por tipo/status.
- Detalhes, edição, histórico de atualizações, exclusão com confirmação.
- **Status**: Andamento · Atrasado · Concluído (conclusão pede confirmação, registra data/hora e **arquiva**).
- **Processos concluídos**: consulta, reabertura e exclusão definitiva separada (somente admin, digitando o protocolo).
- **Lembretes** ao entrar no sistema (atualizam a cada alteração, a cada 5 min e ao voltar para a aba).

### Regras dos alertas (ajustáveis por administradores em *⚙️ Prazos*)

| Nível | Regra padrão | Cor |
|---|---|---|
| Atenção | sem atualização há ≥ 2 dias | amarelo |
| Alerta | sem atualização há ≥ 5 dias | amarelo |
| Atrasado | status Atrasado **ou** prazo de resolução vencido | vermelho |
| Prioridade alta | atrasado há ≥ 3 dias de prazo (ou atrasado e parado ≥ 5 dias) | vermelho |

"Tempo parado" usa `atualizado_em`; "atraso" usa apenas o campo **Prazo de resolução**. Um processo antigo,
porém movimentado e dentro do prazo, **não** é atrasado. Processos em Andamento com prazo vencido viram
*Atrasado* automaticamente (backend). Processos sem prazo aparecem em uma nota cinza informativa.

## Segurança e LGPD

- Login obrigatório; todas as rotas e a API exigem sessão (401/redirecionamento). Sessão `HttpOnly`, `SameSite=Lax`,
  expira por inatividade (30 min), `Secure` configurável; sessão renovada no login.
- Senhas dos usuários com hash (Werkzeug/scrypt); bloqueio após 5 falhas em 15 min; sem senha padrão.
- **Senha do cliente**: opcional (minimização de dados), criptografada com Fernet (AES) no banco, **nunca** enviada em
  listas/detalhes; só é buscada ao clicar em "Revelar" por perfil autorizado (`REVEAL_ROLES`, padrão `admin`), ocultada
  após 15 s e registrada na auditoria.
- Proteção CSRF (token de sessão em formulários e header `X-CSRF-Token`), consultas SQL parametrizadas,
  XSS mitigado (DOM via `textContent`) e CSP restritiva (`script-src 'self'`), `X-Frame-Options: DENY`.
- Trilha de auditoria (`auditoria`): login, visualização, criação, edição, status, revelação de senha, exclusão.
- Direito de eliminação: exclusão definitiva disponível; defina a política de retenção da empresa para os arquivados.
- Sem dados reais ou de demonstração no repositório. Em produção use **HTTPS**, `SESSION_COOKIE_SECURE=1`,
  um servidor WSGI (ex.: `waitress`) e backups criptografados.
