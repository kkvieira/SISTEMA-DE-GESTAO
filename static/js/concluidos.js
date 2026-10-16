/* Página "Processos concluídos": consulta ao arquivo. */
(() => {
  'use strict';
  const { $, h, api, carregando, renderLista } = window.Gestao;
  const filtro = { q: '', tipo: '' };
  let reqId = 0;

  async function carregar() {
    const alvo = $('#lista');
    carregando(alvo);
    const meu = ++reqId;
    const params = new URLSearchParams({ arquivados: '1' });
    if (filtro.q) params.set('q', filtro.q);
    if (filtro.tipo) params.set('tipo', filtro.tipo);
    try {
      const procs = await api(`/api/processos?${params}`);
      if (meu !== reqId) return;
      const vazio = filtro.q || filtro.tipo ? 'Nenhum resultado encontrado para a busca.' : 'Nenhum processo concluído ainda.';
      renderLista(alvo, procs, { arquivados: true, vazio });
    } catch (e) {
      if (meu === reqId) alvo.replaceChildren(h('p', { class: 'erro-txt', text: e.message }));
    }
  }

  window.Gestao.onChange = carregar;
  let t;
  $('#busca').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { filtro.q = e.target.value.trim(); carregar(); }, 300); });
  $('#filtro-tipo').addEventListener('change', (e) => { filtro.tipo = e.target.value; carregar(); });
  carregar();
})();
