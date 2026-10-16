/* Página inicial: resumo, lembretes, cadastro, pastas, busca e listagem. */
(() => {
  'use strict';
  const { $, $$, h, api, toast, busy, carregando, fmtData, tempo, somaDias, aplicarMascaras,
    validarProcesso, limparErros, mostrarErros, lerForm, renderLista, abrirDetalhe, confirmar, APP } = window.Gestao;

  let cfg = { prazo_padrao_dias: 7 };
  const filtro = { tipo: '', q: '', status: '' };
  let reqId = 0, mostrarTodos = false, ultimoAlerta = null;

  // ---------- Painel: resumo + lembretes ----------
  async function carregarPainel() {
    try {
      const [res, al] = await Promise.all([api('/api/resumo'), api('/api/alertas')]);
      renderResumo(res);
      ultimoAlerta = al;
      renderAlertas(al);
    } catch (e) { toast(e.message, 'erro'); }
  }

  function renderResumo(r) {
    $('#st-ativos').textContent = r.ativos;
    $('#st-andamento').textContent = r.andamento;
    $('#st-atrasados').textContent = r.atrasados;
    $('#st-concluidos').textContent = r.concluidos;
    $('#total-txt').textContent = `${r.ativos} ${r.ativos === 1 ? 'processo ativo' : 'processos ativos'}`;
    for (const [tipo, n] of Object.entries(r.por_tipo)) {
      const el = $(`[data-count="${tipo}"]`);
      if (el) el.textContent = n;
    }
  }

  function itemAlerta(i) {
    return h('button', { type: 'button', class: `alert-item alert-${i.cor}`, onclick: () => abrirDetalhe(i.id) },
      h('span', { class: 'dot' }),
      h('span', { class: 'alert-main' },
        h('span', { class: 'alert-line' }, h('strong', { text: i.cliente_nome }), h('code', { text: i.protocolo }), h('span', { class: 'muted', text: i.tipo_label })),
        h('span', { class: 'alert-meta' },
          `Status: ${i.status_label} · Criado em ${fmtData(i.criado_em)} · Última atualização ${tempo(i.atualizado_em)}`),
        h('span', { class: 'alert-motivo', text: i.motivo })),
      h('span', { class: `badge badge-${i.cor}`, text: i.nivel_label }));
  }

  function renderAlertas(al) {
    const corpo = $('#alertas-corpo');
    const partes = [];
    if (al.total === 0) {
      partes.push(h('div', { class: 'allgood' }, 'Tudo em dia! Nenhum processo precisa de atenção no momento.'));
    } else {
      const resumo = al.total === 1 ? 'Você tem 1 processo que precisa de atenção.' : `Você tem ${al.total} processos que precisam de atenção.`;
      partes.push(h('div', { class: 'alert-summary' }, h('strong', { text: resumo }),
        h('span', { class: 'chips' },
          al.vermelhos ? h('span', { class: 'badge badge-vermelho', text: `${al.vermelhos} atrasado(s)` }) : null,
          al.amarelos ? h('span', { class: 'badge badge-amarelo', text: `${al.amarelos} parado(s)` }) : null)));
      const itens = mostrarTodos ? al.itens : al.itens.slice(0, 5);
      partes.push(h('div', { class: 'alert-list' }, itens.map(itemAlerta)));
      if (al.itens.length > 5) {
        partes.push(h('button', { class: 'btn btn-ghost btn-sm', type: 'button',
          text: mostrarTodos ? 'Mostrar menos' : `Ver todos (${al.itens.length})`,
          onclick: () => { mostrarTodos = !mostrarTodos; renderAlertas(ultimoAlerta); } }));
      }
    }
    if (al.sem_prazo > 0) {
      partes.push(h('p', { class: 'info-gray' }, `ℹ${al.sem_prazo} ${al.sem_prazo === 1 ? 'processo está' : 'processos estão'} sem prazo de resolução definido.`));
    }
    corpo.replaceChildren(...partes);
  }

  // ---------- Pastas / busca / lista ----------
  const modoLista = () => Boolean(filtro.tipo || filtro.q || filtro.status);

  async function atualizarVisao() {
    const lista = modoLista();
    $('#pastas').hidden = lista;
    $('#lista-area').hidden = !lista;
    if (!lista) return;
    $('#lista-titulo').textContent = filtro.tipo
      ? `${APP.tipos[filtro.tipo].label}`
      : 'Resultados da busca';
    const alvo = $('#lista');
    carregando(alvo);
    const meu = ++reqId;
    const params = new URLSearchParams();
    Object.entries(filtro).forEach(([k, v]) => { if (v) params.set(k, v); });
    try {
      const procs = await api(`/api/processos?${params}`);
      if (meu !== reqId) return;
      const vazio = filtro.tipo && !filtro.q && !filtro.status
        ? 'Nenhum processo cadastrado nesta categoria.'
        : 'Nenhum resultado encontrado para a busca.';
      renderLista(alvo, procs, { mostrarTipo: !filtro.tipo, vazio });
    } catch (e) {
      if (meu === reqId) alvo.replaceChildren(h('p', { class: 'erro-txt', text: e.message }));
    }
  }

  function iniciarFiltros() {
    $$('.folder').forEach((b) => b.addEventListener('click', () => {
      filtro.tipo = b.dataset.tipo;
      $('#filtro-tipo').value = filtro.tipo;
      atualizarVisao();
    }));
    $('#btn-voltar').addEventListener('click', () => {
      Object.assign(filtro, { tipo: '', q: '', status: '' });
      $('#busca').value = ''; $('#filtro-tipo').value = ''; $('#filtro-status').value = '';
      atualizarVisao();
    });
    let t;
    $('#busca').addEventListener('input', (e) => {
      clearTimeout(t);
      t = setTimeout(() => { filtro.q = e.target.value.trim(); atualizarVisao(); }, 300);
    });
    $('#filtro-tipo').addEventListener('change', (e) => { filtro.tipo = e.target.value; atualizarVisao(); });
    $('#filtro-status').addEventListener('change', (e) => { filtro.status = e.target.value; atualizarVisao(); });
  }

  // ---------- Cadastro ----------
  function valoresPadrao() {
    const f = $('#form-novo');
    f.elements.status.value = 'andamento';
    f.elements.prazo_resolucao.value = somaDias(cfg.prazo_padrao_dias);
  }

  function iniciarCadastro() {
    const form = $('#form-novo');
    aplicarMascaras(form);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      limparErros(form);
      const dados = lerForm(form);
      const erros = validarProcesso(dados, { novo: true });
      if (Object.keys(erros).length) { mostrarErros(form, erros); toast('Corrija os campos destacados.', 'erro'); return; }
      if (dados.status === 'concluido') {
        const ok = await confirmar({ titulo: 'Concluir processo', mensagem: 'Cadastrar já como Concluído? O processo será arquivado imediatamente.', textoOk: 'Cadastrar e arquivar' });
        if (!ok) return;
        dados.confirmar = true;
      }
      const btn = $('#btn-adicionar');
      busy(btn, true);
      try {
        const r = await api('/api/processos', { method: 'POST', body: dados });
        toast(r.mensagem);
        form.reset(); valoresPadrao();
        recarregar();
      } catch (e) {
        mostrarErros(form, e.campos);
        toast(e.message, 'erro');
      } finally { busy(btn, false); }
    });
  }

  // ---------- Configurações (admin) ----------
  function iniciarConfig() {
    const btn = $('#btn-config');
    if (!btn) return;
    const dlg = $('#dlg-config'), form = $('#form-config');
    btn.addEventListener('click', () => {
      limparErros(form);
      for (const el of form.elements) if (el.name) el.value = cfg[el.name] ?? '';
      dlg.showModal();
    });
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      limparErros(form);
      const b = form.querySelector('[type=submit]');
      busy(b, true);
      try {
        const body = Object.fromEntries(Array.from(form.elements).filter((e) => e.name).map((e) => [e.name, e.value]));
        cfg = await api('/api/configuracoes', { method: 'PUT', body });
        toast('Prazos atualizados.');
        dlg.close();
        carregarPainel();
      } catch (e) { mostrarErros(form, e.campos); toast(e.message, 'erro'); }
      finally { busy(b, false); }
    });
  }

  function recarregar() {
    carregarPainel();
    if (modoLista()) atualizarVisao();
  }

  // ---------- Início ----------
  async function iniciar() {
    window.Gestao.onChange = recarregar;
    iniciarFiltros();
    iniciarCadastro();
    iniciarConfig();
    try { cfg = await api('/api/configuracoes'); } catch { /* usa padrão */ }
    valoresPadrao();
    carregarPainel();
    setInterval(carregarPainel, 5 * 60 * 1000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) recarregar(); });
  }
  iniciar();
})();
