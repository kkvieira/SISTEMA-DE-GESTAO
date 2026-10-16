/* Utilitários compartilhados: API, DOM seguro, toasts, máscaras, validação, detalhes/edição de processos. */
(() => {
  'use strict';

  const APP = JSON.parse(document.body.dataset.app || '{}');
  const CSRF = document.querySelector('meta[name="csrf-token"]').content;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /** Cria elementos sem innerHTML (evita XSS: todo texto entra via textContent). */
  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  async function api(url, { method = 'GET', body } = {}) {
    const opts = { method, credentials: 'same-origin', headers: { Accept: 'application/json', 'X-CSRF-Token': CSRF } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let resp;
    try { resp = await fetch(url, opts); }
    catch { throw Object.assign(new Error('Sem conexão com o servidor.'), { status: 0, campos: {} }); }
    let data = null;
    try { data = await resp.json(); } catch { /* sem corpo */ }
    if (resp.status === 401) { location.href = '/login'; throw new Error('Sessão expirada.'); }
    if (!resp.ok) {
      throw Object.assign(new Error((data && data.erro) || 'Erro inesperado.'),
        { status: resp.status, campos: (data && data.campos) || {}, data });
    }
    return data;
  }

  // ---------- Formatação ----------
  const fmtData = (iso) => iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
  const fmtDia = (d) => d ? d.split('-').reverse().join('/') : '—';
  function tempo(iso) {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'agora há pouco';
    const m = Math.floor(s / 60); if (m < 60) return `há ${m} min`;
    const hr = Math.floor(m / 60); if (hr < 24) return `há ${hr} h`;
    const d = Math.floor(hr / 24); return `há ${d} ${d === 1 ? 'dia' : 'dias'}`;
  }
  const hoje = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const somaDias = (n) => { const d = new Date(); d.setDate(d.getDate() + n); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };

  function toast(msg, tipo = 'ok') {
    const el = h('div', { class: `toast toast-${tipo}`, role: tipo === 'erro' ? 'alert' : 'status' },
      h('span', { text: tipo === 'erro' ? '' : tipo === 'info' ? 'ℹ' : '' }), h('span', { text: msg }));
    $('#toasts').append(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, 4500);
  }

  function busy(btn, on) {
    if (!btn) return;
    btn.disabled = on;
    btn.classList.toggle('loading', on);
    btn.setAttribute('aria-busy', on ? 'true' : 'false');
  }
  const carregando = (el, txt = 'Carregando…') =>
    el.replaceChildren(h('div', { class: 'loading-box' }, h('span', { class: 'spinner' }), txt));

  // ---------- Máscaras e validação ----------
  const digitos = (v) => String(v || '').replace(/\D/g, '');
  const maskCpf = (v) => digitos(v).slice(0, 11).replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d{1,2})$/, '$1-$2');
  const maskCnpj = (v) => digitos(v).slice(0, 14).replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2').replace(/(\d{4})(\d)/, '$1-$2');

  function cpfValido(v) {
    const c = digitos(v);
    if (c.length !== 11 || /^(\d)\1+$/.test(c)) return false;
    for (const i of [9, 10]) {
      let s = 0; for (let n = 0; n < i; n++) s += +c[n] * (i + 1 - n);
      if (+c[i] !== (s * 10 % 11) % 10) return false;
    }
    return true;
  }
  function cnpjValido(v) {
    const c = digitos(v);
    if (c.length !== 14 || /^(\d)\1+$/.test(c)) return false;
    const p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], p2 = [6, ...p1];
    for (const [i, p] of [[12, p1], [13, p2]]) {
      let s = 0; for (let n = 0; n < i; n++) s += +c[n] * p[n];
      const d = s % 11 < 2 ? 0 : 11 - (s % 11);
      if (+c[i] !== d) return false;
    }
    return true;
  }

  function aplicarMascaras(raiz = document) {
    $$('[data-mask]', raiz).forEach((el) => {
      el.addEventListener('input', () => { el.value = el.dataset.mask === 'cpf' ? maskCpf(el.value) : maskCnpj(el.value); });
    });
  }

  function validarProcesso(d, { novo }) {
    const e = {};
    const nome = (d.cliente_nome || '').trim().split(/\s+/).filter(Boolean);
    if (!nome.length) e.cliente_nome = 'Informe o nome completo do cliente.';
    else if (nome.length < 2) e.cliente_nome = 'Informe nome e sobrenome.';
    if (!digitos(d.cpf) && !digitos(d.cnpj)) { e.cpf = 'Informe o CPF ou o CNPJ.'; e.cnpj = 'Informe o CPF ou o CNPJ.'; }
    if (digitos(d.cpf) && !cpfValido(d.cpf)) e.cpf = 'CPF inválido.';
    if (digitos(d.cnpj) && !cnpjValido(d.cnpj)) e.cnpj = 'CNPJ inválido.';
    if (!(d.plano || '').trim()) e.plano = 'Informe o nome do plano de saúde.';
    const prot = (d.protocolo || '').trim();
    if (!prot) e.protocolo = 'Informe o número do protocolo.';
    else if (!/^[A-Za-z0-9][A-Za-z0-9./_-]{2,39}$/.test(prot)) e.protocolo = 'Use 3 a 40 caracteres: letras, números, ponto, barra ou hífen.';
    if (!d.tipo) e.tipo = 'Selecione o tipo de processo.';
    if (!d.status) e.status = 'Selecione o status do processo.';
    if (novo && d.status === 'andamento' && d.prazo_resolucao && d.prazo_resolucao < hoje())
      e.prazo_resolucao = 'O prazo não pode estar no passado para um processo em andamento.';
    return e;
  }

  function limparErros(form) {
    $$('.erro', form).forEach((e) => { e.textContent = ''; });
    $$('.invalid', form).forEach((e) => e.classList.remove('invalid'));
  }
  function mostrarErros(form, campos) {
    for (const [nome, msg] of Object.entries(campos || {})) {
      const alvo = form.querySelector(`[data-erro="${nome}"]`);
      if (alvo) alvo.textContent = msg;
      const campo = form.elements[nome];
      if (campo) campo.classList.add('invalid');
    }
    const primeiro = form.querySelector('.invalid');
    if (primeiro) primeiro.focus();
  }
  function lerForm(form) {
    const o = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      o[el.name] = el.type === 'checkbox' ? el.checked : el.value;
    }
    return o;
  }
  function preencherForm(form, p) {
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === 'checkbox') el.checked = false;
      else if (el.name === 'senha_cliente') el.value = '';
      else el.value = p[el.name] ?? '';
    }
  }

  // ---------- Janelas ----------
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-fechar]');
    if (b) b.closest('dialog').close();
    else if (e.target.tagName === 'DIALOG') e.target.close(); // clique no fundo
  });

  function confirmar({ titulo = 'Confirmar', mensagem, textoOk = 'Confirmar', perigo = false, digite = null }) {
    return new Promise((resolve) => {
      const dlg = $('#dlg-confirmar'), ok = $('#conf-ok'), input = $('#conf-input');
      $('#conf-titulo').textContent = titulo;
      $('#conf-msg').textContent = mensagem;
      $('#conf-digite').hidden = !digite;
      input.value = ''; input.classList.remove('invalid');
      if (digite) $('#conf-label').textContent = `Digite "${digite}" para confirmar:`;
      ok.className = `btn ${perigo ? 'btn-danger' : 'btn-primary'}`;
      ok.textContent = textoOk;
      let fim = false;
      const encerrar = (v) => { if (fim) return; fim = true; dlg.close(); resolve(v); };
      ok.onclick = () => {
        if (digite && input.value.trim().toLowerCase() !== digite.toLowerCase()) { input.classList.add('invalid'); input.focus(); return; }
        encerrar(digite ? input.value.trim() : true);
      };
      $('#conf-cancelar').onclick = () => encerrar(false);
      dlg.onclose = () => encerrar(false);
      dlg.showModal();
      (digite ? input : ok).focus();
    });
  }

  // ---------- Selos e listas ----------
  const badgeStatus = (s, label) => h('span', { class: `badge badge-${s}`, text: label });

  function renderLista(el, procs, { mostrarTipo = true, arquivados = false, vazio = 'Nenhum processo encontrado.' } = {}) {
    if (!procs.length) {
      el.replaceChildren(h('div', { class: 'empty' }, h('div', { class: 'empty-icon', text: '' }), h('p', { text: vazio })));
      return;
    }
    const cols = ['Cliente', 'Plano', 'Protocolo', ...(mostrarTipo ? ['Tipo'] : []), 'Cadastro', arquivados ? 'Concluído em' : 'Status', ''];
    const thead = h('thead', {}, h('tr', {}, cols.map((c) => h('th', { text: c }))));
    const linhas = procs.map((p) => {
      const abrir = () => abrirDetalhe(p.id);
      const cel = (label, ...c) => h('td', { 'data-label': label }, ...c);
      return h('tr', { class: 'row-click', tabindex: '0', onclick: abrir, onkeydown: (e) => { if (e.key === 'Enter') abrir(); } },
        cel('Cliente', h('strong', { text: p.cliente_nome })),
        cel('Plano', p.plano),
        cel('Protocolo', h('code', { text: p.protocolo })),
        mostrarTipo ? cel('Tipo', p.tipo_label) : null,
        cel('Cadastro', fmtData(p.criado_em)),
        cel(arquivados ? 'Concluído em' : 'Status', arquivados ? fmtData(p.concluido_em) : badgeStatus(p.status, p.status_label)),
        h('td', { class: 'td-acao' }, h('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Ver detalhes' })));
    });
    el.replaceChildren(h('div', { class: 'table-wrap' }, h('table', { class: 'tabela' }, thead, h('tbody', {}, linhas))));
  }

  // ---------- Detalhes ----------
  const G = { onChange: null };
  const mudou = () => { if (typeof G.onChange === 'function') G.onChange(); };

  async function abrirDetalhe(id) {
    const dlg = $('#dlg-detalhe'), corpo = $('#det-corpo');
    carregando(corpo);
    if (!dlg.open) dlg.showModal();
    try {
      renderDetalhe(await api(`/api/processos/${id}`));
    } catch (e) {
      corpo.replaceChildren(h('p', { class: 'erro-txt', text: e.message }));
    }
  }

  function campoDetalhe(rotulo, valor, largo = false) {
    return h('div', { class: `kv${largo ? ' kv-wide' : ''}` }, h('dt', { text: rotulo }), h('dd', {}, valor));
  }

  function renderDetalhe(p) {
    const arq = p.status === 'concluido';
    $('#det-titulo').textContent = `Protocolo ${p.protocolo}`;

    // Senha: nunca vem na resposta; só é buscada sob demanda e por perfil autorizado.
    let senhaEl = h('span', { class: 'mono', text: p.tem_senha ? '••••••••' : '—' });
    let senhaBtn = null;
    if (p.tem_senha && p.pode_ver_senha) {
      let timer = null, visivel = false;
      senhaBtn = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Revelar' });
      senhaBtn.addEventListener('click', async () => {
        if (visivel) { senhaEl.textContent = '••••••••'; senhaBtn.textContent = 'Revelar'; visivel = false; clearTimeout(timer); return; }
        busy(senhaBtn, true);
        try {
          const r = await api(`/api/processos/${p.id}/senha`, { method: 'POST', body: {} });
          senhaEl.textContent = r.senha; senhaBtn.textContent = 'Ocultar'; visivel = true;
          timer = setTimeout(() => { senhaEl.textContent = '••••••••'; senhaBtn.textContent = 'Revelar'; visivel = false; }, 15000);
        } catch (e) { toast(e.message, 'erro'); } finally { busy(senhaBtn, false); }
      });
    }

    const prazo = h('span', {}, fmtDia(p.prazo_resolucao), ' ',
      p.prazo_vencido ? h('span', { class: 'badge badge-atrasado', text: 'vencido' }) : null);

    const dl = h('dl', { class: 'kvs' },
      campoDetalhe('Cliente', p.cliente_nome, true),
      campoDetalhe('CPF', p.cpf || '—'), campoDetalhe('CNPJ', p.cnpj || '—'),
      campoDetalhe('Plano de saúde', p.plano), campoDetalhe('Tipo de processo', p.tipo_label),
      campoDetalhe('Login do cliente', p.login_cliente || '—'),
      campoDetalhe('Senha do cliente', h('span', { class: 'inline' }, senhaEl, senhaBtn)),
      campoDetalhe('Status', badgeStatus(p.status, p.status_label)),
      campoDetalhe('Prazo de resolução', prazo),
      campoDetalhe('Cadastrado em', fmtData(p.criado_em)),
      campoDetalhe('Última atualização', `${fmtData(p.atualizado_em)} (${tempo(p.atualizado_em)})`),
      arq ? campoDetalhe('Concluído em', fmtData(p.concluido_em)) : null);

    const blocos = [dl];

    if (!arq) {
      const sel = h('select', { id: 'det-status', 'aria-label': 'Novo status' },
        Object.entries(APP.status).map(([k, v]) => h('option', { value: k, text: v, selected: k === p.status })));
      const btnStatus = h('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Atualizar status' });
      btnStatus.addEventListener('click', async () => {
        busy(btnStatus, true);
        try { await mudarStatus(p, sel.value); } finally { busy(btnStatus, false); }
      });

      const txt = h('textarea', { id: 'det-nota', rows: '2', maxlength: '1000', placeholder: 'Ex.: Aguardando retorno da operadora…' });
      const btnNota = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Registrar atualização' });
      btnNota.addEventListener('click', async () => {
        if (!txt.value.trim()) { toast('Escreva a atualização antes de salvar.', 'erro'); txt.focus(); return; }
        busy(btnNota, true);
        try {
          const r = await api(`/api/processos/${p.id}/atualizacoes`, { method: 'POST', body: { texto: txt.value } });
          toast(r.mensagem); mudou(); await abrirDetalhe(p.id);
        } catch (e) { toast(e.message, 'erro'); busy(btnNota, false); }
      });

      blocos.push(
        h('div', { class: 'det-box' }, h('h4', { text: 'Status' }), h('div', { class: 'inline' }, sel, btnStatus)),
        h('div', { class: 'det-box' }, h('h4', { text: 'Registrar atualização' }), txt, h('div', { class: 'right' }, btnNota)));
    }

    const acoes = h('div', { class: 'dlg-actions' });
    if (arq) {
      const reabrir = h('button', { class: 'btn btn-primary', type: 'button', text: 'Reabrir processo' });
      reabrir.addEventListener('click', async () => {
        busy(reabrir, true);
        try { const r = await api(`/api/processos/${p.id}/reabrir`, { method: 'POST', body: {} }); toast(r.mensagem); $('#dlg-detalhe').close(); mudou(); }
        catch (e) { toast(e.message, 'erro'); busy(reabrir, false); }
      });
      acoes.append(reabrir);
    } else {
      acoes.append(h('button', { class: 'btn btn-ghost', type: 'button', text: 'Editar', onclick: () => abrirEdicao(p) }));
    }
    if (!arq || APP.admin) {
      acoes.append(h('button', { class: 'btn btn-danger', type: 'button', text: arq ? 'Excluir definitivamente' : 'Excluir', onclick: () => excluir(p) }));
    }
    blocos.push(acoes);

    const hist = h('div', { class: 'det-box' }, h('h4', { text: 'Histórico' }),
      h('ul', { class: 'historico' }, (p.historico || []).map((x) =>
        h('li', {}, h('time', { text: fmtData(x.criado_em) }), h('span', { class: 'quem', text: x.usuario }), h('span', { text: x.texto })))));
    blocos.push(hist);

    $('#det-corpo').replaceChildren(...blocos);
  }

  async function mudarStatus(p, novo) {
    if (novo === p.status) { toast('O status já é este.', 'info'); return; }
    const body = { status: novo };
    if (novo === 'concluido') {
      const ok = await confirmar({
        titulo: 'Concluir processo',
        mensagem: `Concluir o processo ${p.protocolo}? Ele será arquivado, sairá das pastas e dos lembretes e ficará disponível em "Processos concluídos".`,
        textoOk: 'Concluir e arquivar',
      });
      if (!ok) return;
      body.confirmar = true;
    }
    try {
      const r = await api(`/api/processos/${p.id}/status`, { method: 'PATCH', body });
      toast(r.mensagem);
      mudou();
      if (novo === 'concluido') $('#dlg-detalhe').close(); else await abrirDetalhe(p.id);
    } catch (e) { toast(e.message, 'erro'); }
  }

  async function excluir(p) {
    const arq = p.status === 'concluido';
    const r = await confirmar({
      titulo: arq ? 'Exclusão definitiva' : 'Excluir processo',
      mensagem: arq
        ? 'Os dados deste processo arquivado serão apagados de forma permanente e não poderão ser recuperados. Exclua apenas se a política de retenção de dados permitir.'
        : `Excluir o processo ${p.protocolo} de ${p.cliente_nome}? Esta ação não pode ser desfeita.`,
      textoOk: 'Excluir', perigo: true, digite: arq ? p.protocolo : null,
    });
    if (!r) return;
    try {
      const resp = await api(`/api/processos/${p.id}`, { method: 'DELETE', body: arq ? { confirmacao: r } : { confirmar: true } });
      toast(resp.mensagem); $('#dlg-detalhe').close(); mudou();
    } catch (e) { toast(e.message, 'erro'); }
  }

  // ---------- Edição ----------
  function abrirEdicao(p) {
    const form = $('#form-editar');
    limparErros(form);
    preencherForm(form, p);
    form.dataset.id = p.id;
    $('#dlg-editar').showModal();
  }

  function iniciarEdicao() {
    const form = $('#form-editar');
    if (!form) return;
    aplicarMascaras(form);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      limparErros(form);
      const dados = lerForm(form);
      const erros = validarProcesso(dados, { novo: false });
      if (Object.keys(erros).length) { mostrarErros(form, erros); toast('Corrija os campos destacados.', 'erro'); return; }
      if (dados.status === 'concluido') {
        const ok = await confirmar({ titulo: 'Concluir processo', mensagem: 'Ao salvar como Concluído o processo será arquivado e sairá dos lembretes. Continuar?', textoOk: 'Concluir e arquivar' });
        if (!ok) return;
        dados.confirmar = true;
      }
      const btn = form.querySelector('[type=submit]');
      busy(btn, true);
      try {
        const r = await api(`/api/processos/${form.dataset.id}`, { method: 'PUT', body: dados });
        toast(r.mensagem);
        $('#dlg-editar').close();
        mudou();
        if (dados.status === 'concluido') $('#dlg-detalhe').close(); else abrirDetalhe(form.dataset.id);
      } catch (e) {
        mostrarErros(form, e.campos);
        toast(e.message, 'erro');
      } finally { busy(btn, false); }
    });
  }

  Object.assign(G, {
    APP, $, $$, h, api, toast, busy, carregando, confirmar, fmtData, fmtDia, tempo, hoje, somaDias,
    aplicarMascaras, validarProcesso, limparErros, mostrarErros, lerForm, renderLista, abrirDetalhe, badgeStatus,
  });
  window.Gestao = G;
  iniciarEdicao();
})();
