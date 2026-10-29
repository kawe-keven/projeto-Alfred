const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

// Application state
let voiceRunning = false;
let voiceMuted = false;
let chatBusy = false;
let toastTimer;
let previewAudio;
let lastLatency;
let voicePhase = 'parado';
let systemUnavailable = false;
let cliError = false;
let voiceError = false;
let voiceStartPending = false;
let voiceStopRequested = false;
let memoryGraphTimer;
let memoryGraph = null;
let memoryRotation = { x: -0.18, y: 0.42 };
let memoryZoom = 1;
let memoryPointer = null;
let memoryHovered = -1;

const NAV_LABELS = {
  cli: 'TERMINAL',
  voice: 'VOZ ALFRED',
  memory: 'MEMÓRIA VETORIAL',
  map: 'MAPA',
  settings: 'CONFIGURAÇÃO',
};

const VOICE_STATUS = {
  ouvindo: ['ESCUTANDO', 'Pode falar. Estou ouvindo.', 'Áudio capturado e processado localmente.'],
  transcrevendo: ['ANALISANDO ÁUDIO', 'Entendendo sua mensagem.', 'Transcrição local em andamento.'],
  pensando: ['PROCESSANDO', 'Estou preparando uma resposta.', 'Consultando o modelo local.'],
  falando: ['ALFRED FALANDO', 'À sua disposição.', 'Resposta em áudio gerada localmente.'],
  ocioso: ['ESCUTA ATIVA', 'O Alfred está ouvindo.', 'A captura e o processamento acontecem localmente.'],
};

// Local API and interface feedback
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get('content-type') || '';
  if (!response.ok) {
    const error = type.includes('json') ? await response.json() : { error: 'A solicitação não foi concluída.' };
    throw new Error(error.error || error.reason || 'A solicitação não foi concluída.');
  }
  return type.includes('json') ? response.json() : response.blob();
}

function notify(message) {
  $('#toast-text').textContent = message;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3400);
}

function setTab(name) {
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.tab === name));
  $$('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
  $('#page-label').textContent = NAV_LABELS[name] || NAV_LABELS.cli;
  history.replaceState(null, '', `#${name}`);
  if (name === 'settings' && !$('#engine').dataset.loaded) loadCatalog();
  if (name === 'memory') {
    updateMemoryGraph();
    requestAnimationFrame(drawMemoryGraph);
  }
  window.alfredMapa?.setActive(name === 'map');
}

// Mantenha o mapa sincronizado mesmo quando a aba de memória não está aberta
// ou uma sessão de conversa ainda não foi iniciada.
memoryGraphTimer = setInterval(updateMemoryGraph, 3000);

// Navigation and terminal conversation
$$('[data-tab]').forEach(button => button.addEventListener('click', () => setTab(button.dataset.tab)));
$$('[data-prompt]').forEach(button => button.addEventListener('click', () => sendMessage(button.dataset.prompt)));

async function updateMemoryGraph(force = false) {
  try {
    const snapshot = await api(`/api/memory/graph${force ? '?refresh=1' : ''}`);
    if (!snapshot.available) {
      memoryGraph = null;
      $('#memory-status').textContent = 'AGUARDANDO SESSÃO LOCAL';
      $('#memory-live-dot').style.color = 'var(--amber)';
      $('#memory-empty').hidden = false;
      $('#memory-empty strong').textContent = 'Memória aguardando atividade';
      $('#memory-empty p').textContent = snapshot.reason || 'O índice vetorial local ainda não está disponível.';
      $('#memory-node-count').textContent = '0 VETORES · 0 LIGAÇÕES';
      drawMemoryGraph();
      return;
    }
    memoryGraph = snapshot;
    $('#memory-status').textContent = snapshot.warning
      ? 'MEMÓRIA PERSISTENTE INDISPONÍVEL'
      : 'ÍNDICE ATIVO · ATUALIZAÇÃO AUTOMÁTICA';
    $('#memory-live-dot').style.color = snapshot.warning ? 'var(--amber)' : 'var(--cyan)';
    $('#memory-node-count').textContent = `${snapshot.nodes.length.toLocaleString('pt-BR')} VETORES · ${snapshot.edges.length.toLocaleString('pt-BR')} LIGAÇÕES`;
    $('#memory-updated').textContent = `${snapshot.dimension} DIMENSÕES · ATUALIZADO ÀS ${new Date().toLocaleTimeString('pt-BR')}`;
    $('#memory-empty').hidden = snapshot.nodes.length > 0;
    if (memoryHovered >= snapshot.nodes.length) memoryHovered = -1;
    if (!snapshot.nodes.length) {
      $('#memory-empty strong').textContent = 'Índice vetorial sem pontos';
      $('#memory-empty p').textContent = snapshot.warning || 'Os vetores aparecerão aqui conforme forem registrados.';
    }
    drawMemoryGraph();
  } catch (error) {
    $('#memory-status').textContent = 'RECONEXÃO COM A MEMÓRIA';
    $('#memory-live-dot').style.color = 'var(--amber)';
    $('#memory-updated').textContent = error.message || 'Não foi possível atualizar o gráfico.';
    $('#memory-empty').hidden = false;
    $('#memory-empty strong').textContent = 'Reconectando ao índice vetorial';
    $('#memory-empty p').textContent = error.message || 'O Alfred tentará carregar o gráfico novamente em instantes.';
  }
}

function drawMemoryGraph() {
  const canvas = $('#memory-canvas');
  if (!canvas || !canvas.clientWidth || !canvas.clientHeight) return;
  const escala = window.devicePixelRatio || 1;
  const largura = canvas.clientWidth;
  const altura = canvas.clientHeight;
  if (canvas.width !== Math.round(largura * escala) || canvas.height !== Math.round(altura * escala)) {
    canvas.width = Math.round(largura * escala);
    canvas.height = Math.round(altura * escala);
  }
  const contexto = canvas.getContext('2d');
  contexto.setTransform(escala, 0, 0, escala, 0, 0);
  contexto.clearRect(0, 0, largura, altura);
  if (!memoryGraph?.nodes?.length) return;

  const cores = { memorias: '#65e2d2', conversas: '#69bafa', conhecimento: '#f1bc73', resumos: '#c49bff' };
  const cosX = Math.cos(memoryRotation.x), sinX = Math.sin(memoryRotation.x);
  const cosY = Math.cos(memoryRotation.y), sinY = Math.sin(memoryRotation.y);
  const escalaBase = Math.min(largura, altura) * .34 * memoryZoom;
  const projetados = memoryGraph.nodes.map((node, indice) => {
    const [x, y, z] = node.xyz;
    const rx = x * cosY - z * sinY;
    const rz = x * sinY + z * cosY;
    const ry = y * cosX - rz * sinX;
    const profundidade = y * sinX + rz * cosX;
    const perspectiva = 1.25 / (1.8 - profundidade * .35);
    return { node, indice, x: largura / 2 + rx * escalaBase * perspectiva, y: altura / 2 + ry * escalaBase * perspectiva, perspectiva, profundidade };
  });
  for (const edge of memoryGraph.edges || []) {
    const origem = projetados[edge.source], destino = projetados[edge.target];
    if (!origem || !destino) continue;
    contexto.beginPath();
    contexto.moveTo(origem.x, origem.y);
    contexto.lineTo(destino.x, destino.y);
    contexto.strokeStyle = `rgba(105,186,250,${.08 + Math.min(.35, edge.similarity * .25)})`;
    contexto.lineWidth = .5 + edge.similarity;
    contexto.stroke();
  }
  projetados.sort((a, b) => a.profundidade - b.profundidade);
  for (const ponto of projetados) {
    const raio = Math.max(2, Math.min(6, 2.2 + ponto.perspectiva * 1.7));
    contexto.beginPath();
    contexto.arc(ponto.x, ponto.y, raio, 0, Math.PI * 2);
    contexto.fillStyle = cores[ponto.node.colecao] || '#dce6ee';
    contexto.globalAlpha = ponto.indice === memoryHovered ? 1 : .55 + ponto.perspectiva * .25;
    contexto.shadowBlur = ponto.indice === memoryHovered ? 16 : 7;
    contexto.shadowColor = contexto.fillStyle;
    contexto.fill();
  }
  contexto.globalAlpha = 1;
  contexto.shadowBlur = 0;
}

$('#memory-refresh')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  if (button.disabled) return;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = '↻ ATUALIZANDO…';
  $('#memory-status').textContent = 'ATUALIZANDO ÍNDICE';
  try {
    await updateMemoryGraph(true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
});
$('#memory-canvas')?.addEventListener('pointerdown', event => {
  memoryPointer = { x: event.clientX, y: event.clientY, id: event.pointerId };
  event.currentTarget.setPointerCapture(event.pointerId);
});
$('#memory-canvas')?.addEventListener('pointermove', event => {
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  if (memoryPointer && memoryPointer.id === event.pointerId) {
    memoryRotation.y += (event.clientX - memoryPointer.x) * .008;
    memoryRotation.x += (event.clientY - memoryPointer.y) * .008;
    memoryPointer.x = event.clientX;
    memoryPointer.y = event.clientY;
    drawMemoryGraph();
    return;
  }
  const x = event.clientX - rect.left, y = event.clientY - rect.top;
  let melhor = -1, distancia = 14;
  for (const ponto of memoryGraph?.nodes || []) {
    const [px, py, pz] = ponto.xyz;
    const cosX = Math.cos(memoryRotation.x), sinX = Math.sin(memoryRotation.x);
    const cosY = Math.cos(memoryRotation.y), sinY = Math.sin(memoryRotation.y);
    const rx = px * cosY - pz * sinY, rz = px * sinY + pz * cosY;
    const ry = py * cosX - rz * sinX, profundidade = py * sinX + rz * cosX;
    const perspectiva = 1.25 / (1.8 - profundidade * .35), base = Math.min(rect.width, rect.height) * .34 * memoryZoom;
    const dx = rect.width / 2 + rx * base * perspectiva - x, dy = rect.height / 2 + ry * base * perspectiva - y;
    const d = Math.hypot(dx, dy);
    if (d < distancia) { distancia = d; melhor = memoryGraph.nodes.indexOf(ponto); }
  }
  if (memoryHovered !== melhor) {
    memoryHovered = melhor;
    drawMemoryGraph();
  }
});
$('#memory-canvas')?.addEventListener('pointerup', () => { memoryPointer = null; });
$('#memory-canvas')?.addEventListener('pointercancel', () => { memoryPointer = null; });
$('#memory-canvas')?.addEventListener('wheel', event => {
  event.preventDefault();
  memoryZoom *= event.deltaY > 0 ? .94 : 1.06;
  drawMemoryGraph();
}, { passive: false });
window.addEventListener('resize', drawMemoryGraph);
$$('.mode-option input').forEach(input => input.addEventListener('change', () => {
  $$('.mode-option').forEach(option => option.classList.toggle('selected', option.querySelector('input').checked));
}));

function addMessage(role, text, options = {}) {
  $('#welcome').hidden = true;
  const row = document.createElement('div');
  row.className = `message-row ${role}${options.typing ? ' typing' : ''}`;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'V' : 'A';

  const content = document.createElement('div');
  content.className = 'message-content';

  const meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = `${role === 'user' ? 'VOCÊ' : 'ALFRED'}  ·  ${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  if (options.typing) {
    bubble.innerHTML = '<i></i><i></i><i></i>';
  } else {
    bubble.textContent = text;
  }
  content.append(meta, bubble);
  row.append(avatar, content);
  $('#chat-log').append(row);
  $('#chat-log').scrollTop = $('#chat-log').scrollHeight;
  return { row, bubble };
}

function appendInlineMarkdown(parent, source) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_|~~[^~]+~~|\[[^\]]+\]\([^)]+\))/g;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    parent.append(document.createTextNode(source.slice(cursor, match.index)));
    const token = match[0];
    let element;
    if (token.startsWith('`')) {
      element = document.createElement('code');
      element.textContent = token.slice(1, -1);
    } else if (token.startsWith('**') || token.startsWith('__')) {
      element = document.createElement('strong');
      appendInlineMarkdown(element, token.slice(2, -2));
    } else if (token.startsWith('~~')) {
      element = document.createElement('del');
      appendInlineMarkdown(element, token.slice(2, -2));
    } else if (token.startsWith('*') || token.startsWith('_')) {
      element = document.createElement('em');
      appendInlineMarkdown(element, token.slice(1, -1));
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      let url;
      try { url = new URL(link[2], window.location.href); } catch { url = null; }
      if (!url || !['http:', 'https:'].includes(url.protocol)) {
        parent.append(document.createTextNode(token));
        cursor = match.index + token.length;
        continue;
      }
      element = document.createElement('a');
      element.href = url.href;
      element.target = '_blank';
      element.rel = 'noopener noreferrer';
      element.textContent = link[1];
    }
    parent.append(element);
    cursor = match.index + token.length;
  }
  parent.append(document.createTextNode(source.slice(cursor)));
}

function renderMarkdown(target, markdown) {
  const lines = String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n');
  let index = 0;
  const isList = line => /^\s*(?:[-*+]\s+|\d+[.)]\s+)/.test(line);

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }

    const fence = line.match(/^\s*```([^`]*)$/);
    if (fence) {
      index += 1;
      const code = [];
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      const pre = document.createElement('pre');
      const codeElement = document.createElement('code');
      if (fence[1].trim()) codeElement.dataset.language = fence[1].trim().split(/\s+/)[0];
      codeElement.textContent = code.join('\n');
      pre.append(codeElement);
      target.append(pre);
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const element = document.createElement(`h${heading[1].length}`);
      appendInlineMarkdown(element, heading[2]);
      target.append(element);
      index += 1;
      continue;
    }

    if (/^\s{0,3}(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
      target.append(document.createElement('hr'));
      index += 1;
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote = document.createElement('blockquote');
      while (index < lines.length && /^\s*>/.test(lines[index])) {
        const paragraph = document.createElement('p');
        appendInlineMarkdown(paragraph, lines[index++].replace(/^\s*>\s?/, ''));
        quote.append(paragraph);
      }
      target.append(quote);
      continue;
    }

    if (isList(line)) {
      const ordered = /^\s*\d/.test(line);
      const list = document.createElement(ordered ? 'ol' : 'ul');
      while (index < lines.length && isList(lines[index]) && /^\s*\d/.test(lines[index]) === ordered) {
        const item = document.createElement('li');
        appendInlineMarkdown(item, lines[index++].replace(/^\s*(?:[-*+]\s+|\d+[.)]\s+)/, ''));
        list.append(item);
      }
      target.append(list);
      continue;
    }

    const paragraph = document.createElement('p');
    const paragraphLines = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() &&
      !/^\s*```/.test(lines[index]) && !/^\s{0,3}#{1,6}\s/.test(lines[index]) &&
      !/^\s*>/.test(lines[index]) && !isList(lines[index]) &&
      !/^\s{0,3}(?:---+|___+|\*\*\*+)\s*$/.test(lines[index])) {
      paragraphLines.push(lines[index++]);
    }
    appendInlineMarkdown(paragraph, paragraphLines.join('\n'));
    target.append(paragraph);
  }
}

async function sendMessage(text) {
  if (chatBusy) return;
  const input = $('#message');
  const message = (text ?? input.value).trim();
  if (!message) { input.focus(); return; }
  chatBusy = true;
  cliError = false;
  input.value = '';
  updateCount();
  $('#cli-sphere').dataset.sphereState = 'pensando';
  $('#chat-status').textContent = 'PROCESSANDO';
  $('.send-button').disabled = true;
  const mensagemSegura = /^\/(?:configurar_email|configuraremail)(?:\s|$)/i.test(message)
    ? '/configuraremail [credenciais ocultas]'
    : message;
  addMessage('user', mensagemSegura);
  const pending = addMessage('assistant', '', { typing: true });
  const started = performance.now();
  try {
    const result = await api('/api/chat', { method: 'POST', body: JSON.stringify({ text: message }) });
    lastLatency = performance.now() - started;
    pending.row.classList.remove('typing');
    renderMarkdown(pending.bubble, result.reply);
    $('#chat-status').textContent = 'RESPOSTA CONCLUÍDA';
    $('#latency').textContent = `${(lastLatency / 1000).toFixed(1).replace('.', ',')} s`;
  } catch (error) {
    cliError = true;
    pending.row.remove();
    addMessage('assistant', error.message);
    $('#chat-status').textContent = 'ERRO NA SOLICITAÇÃO';
    notify(error.message);
  } finally {
    chatBusy = false;
    atualizarEsferas();
    $('.send-button').disabled = false;
    $('#chat-log').scrollTop = $('#chat-log').scrollHeight;
    input.focus();
  }
}

$('#chat-form').addEventListener('submit', event => { event.preventDefault(); sendMessage(); });
$('#message').addEventListener('input', updateCount);
$('#message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#chat-form').requestSubmit(); }
});
function updateCount() {
  const length = $('#message').value.length;
  $('#char-count').textContent = `${String(length).padStart(4, '0')} / 4000`;
}

async function refreshStatus() {
  try {
    const status = await api('/api/status');
    const ready = status.ollama === 'conectado';
    systemUnavailable = !ready;
    $('#sys-state').textContent = ready ? 'Online' : 'IA local indisponível';
    $('#sys-dot').classList.toggle('online', ready);
    $('#connection-title').textContent = ready ? 'Conectado' : 'Desconectado';
    $('#model-name').textContent = status.model || '—';
    voiceRunning = Boolean(status.voiceRunning);
    voiceMuted = Boolean(status.voiceMuted);
    updateVoiceState();
    atualizarEsferas();
    if (status.confirmation) showConfirmation(status.confirmation.question);
  } catch {
    systemUnavailable = true;
    $('#sys-state').textContent = 'Painel offline';
    $('#connection-title').textContent = 'Indisponível';
    $('#sys-dot').classList.remove('online');
    atualizarEsferas();
  }
}

// System confirmations
function showConfirmation(question) {
  if ($('#confirm-modal').classList.contains('open')) return;
  $('#confirm-question').textContent = question;
  $('#confirm-modal').classList.add('open');
}
async function answerConfirmation(answer) {
  $('#confirm-modal').classList.remove('open');
  try {
    await api('/api/confirm', { method: 'POST', body: JSON.stringify({ answer }) });
  } catch (error) {
    notify(error.message);
  }
}
$('#confirm-yes').addEventListener('click', () => answerConfirmation('sim'));
$('#confirm-no').addEventListener('click', () => answerConfirmation('não'));
$('#refresh').addEventListener('click', () => {
  refreshStatus();
  if ($('#view-settings').classList.contains('active')) loadCatalog(true);
  notify('Estado do sistema atualizado.');
});

// Voice session state and controls
function updateVoiceState() {
  const consoleEl = $('#voice-console');
  consoleEl.classList.toggle('running', voiceRunning);
  consoleEl.classList.toggle('speaking', voicePhase === 'falando');
  consoleEl.classList.toggle('listening', voicePhase === 'ouvindo');
  consoleEl.classList.toggle('error', voiceError || systemUnavailable);
  atualizarEsferas();
  window.alfredMapa?.setVoiceActive(voiceRunning);
  $('#voice-toggle-label').textContent = voiceRunning ? 'ENCERRAR SESSÃO' : 'INICIAR SESSÃO';
  const standby = ['STANDBY', 'Pronto quando você estiver.', 'Inicie a sessão para ativar a captura de voz local.'];
  const visible = voiceRunning ? (VOICE_STATUS[voicePhase] || VOICE_STATUS.ocioso) : standby;
  $('#voice-state-label').textContent = visible[0];
  $('#voice-state').textContent = visible[1];
  $('#voice-detail').textContent = visible[2];
  $('#mute-button').disabled = !voiceRunning;
  $('#mute-button').classList.toggle('muted', voiceMuted);
  $('#mute-button').innerHTML = voiceMuted
    ? '<span>◉</span> REATIVAR'
    : '<span>◌</span> MUDO';
}

function atualizarEsferas() {
  const estadoSistema = systemUnavailable ? 'indisponivel' : null;
  $('#cli-sphere').dataset.sphereState = estadoSistema || (cliError ? 'erro' : chatBusy ? 'pensando' : 'ocioso');
  $('#voice-sphere').dataset.sphereState = estadoSistema || (voiceError ? 'erro' : voicePhase);
  $$('.mini-sphere:not(#cli-sphere)').forEach(sphere => {
    sphere.dataset.sphereState = estadoSistema || (voiceError ? 'erro' : voicePhase === 'falando' ? 'falando' : 'ocioso');
  });
  $('#identity-sphere').dataset.sphereState = estadoSistema || (voiceError ? 'erro' : $('#preview-wave').classList.contains('playing') ? 'falando' : 'ocioso');
}

async function refreshVoiceState() {
  try {
    const current = await api('/api/voice/state');
    const previous = voiceRunning;
    voiceRunning = current.running;
    voiceMuted = current.muted;
    voicePhase = current.state;
    if (voiceRunning) voiceStartPending = false;
    if (!voiceRunning && voiceStartPending) {
      voiceError = true;
      voiceStartPending = false;
    }
    if (previous && !voiceRunning) {
      voiceError = !voiceStopRequested;
      voiceStopRequested = false;
    }
    updateVoiceState();
    if (previous && !voiceRunning) notify(voiceError ? 'A sessão de voz encontrou um erro.' : 'A sessão de voz foi encerrada.');
  } catch {
    // A atualização geral mostrará se o painel foi desconectado.
  }
}

function animateWave(container, count) {
  container.replaceChildren(...Array.from({ length: count }, () => document.createElement('i')));
}
animateWave($('#preview-wave'), 31);

$('#voice-toggle').addEventListener('click', async () => {
  const button = $('#voice-toggle');
  button.disabled = true;
  try {
    if (voiceRunning) {
      voiceStopRequested = true;
    } else {
      voiceStartPending = true;
      voiceError = false;
    }
    const path = voiceRunning ? '/api/voice/stop' : '/api/voice/start';
    const body = voiceRunning ? {} : { mode: $('input[name="mode"]:checked').value };
    const result = await api(path, { method: 'POST', body: JSON.stringify(body) });
    voiceRunning = result.running;
    updateVoiceState();
    notify(result.message);
    if (!voiceRunning) {
      voiceMuted = false;
      voicePhase = 'parado';
      voiceStartPending = false;
      voiceStopRequested = false;
      voiceError = false;
    } else {
      voicePhase = 'iniciando';
    }
    updateVoiceState();
  } catch (error) {
    if (voiceStartPending) {
      voiceStartPending = false;
      voiceError = true;
      updateVoiceState();
    }
    voiceStopRequested = false;
    notify(error.message);
  }
  finally {
    button.disabled = false;
  }
});
$('#mute-button').addEventListener('click', async () => {
  const button = $('#mute-button');
  button.disabled = true;
  try {
    const result = await api('/api/voice/mute', { method: 'POST', body: '{}' });
    voiceMuted = result.muted;
    updateVoiceState();
    notify(result.message);
  } catch (error) { notify(error.message); }
  finally {
    button.disabled = !voiceRunning;
  }
});

function selectedSettings() {
  return {
    model: $('#engine').value,
    voice_id: $('#voice-profile').value,
    speed: Number($('#speed').value),
    seed: Number($('#seed').value),
    style: $('#style').value.trim(),
  };
}

// Voice profile catalog and settings
function updatePreviewIdentity() {
  $('#preview-engine').textContent = $('#engine').selectedOptions[0]?.textContent || '—';
  $('#preview-voice').textContent = $('#voice-profile').selectedOptions[0]?.textContent || '—';
}
$('#engine').addEventListener('change', updatePreviewIdentity);
$('#voice-profile').addEventListener('change', updatePreviewIdentity);
$('#speed').addEventListener('input', () => { $('#speed-output').value = `${Number($('#speed').value).toFixed(2).replace('.', ',')}×`; });

async function loadCatalog(force = false) {
  if ($('#engine').dataset.loaded && !force) return;
  $('#catalog-status').textContent = 'CONECTANDO…';
  try {
    const catalog = await api('/api/voice/catalog');
    const prefs = catalog.preferences || {};
    const engine = $('#engine');
    engine.replaceChildren();
    const profile = $('#voice-profile');
    profile.replaceChildren();
    for (const item of catalog.models) engine.add(new Option(item.label, item.id));
    for (const item of catalog.voices) profile.add(new Option(`${item.label}${item.language ? ` · ${item.language}` : ''}`, item.id));
    if (prefs.model) engine.value = prefs.model;
    if (prefs.voice_id) profile.value = prefs.voice_id;
    $('#speed').value = prefs.speed || 1;
    $('#speed-output').value = `${Number($('#speed').value).toFixed(2).replace('.', ',')}×`;
    $('#seed').value = prefs.seed ?? 42;
    $('#style').value = prefs.style || '';
    engine.dataset.loaded = 'true'; updatePreviewIdentity();
    if (catalog.connected) {
      $('#catalog-status').textContent = `${catalog.voices.length} PERFIS`;
      $('#profile-hint').textContent = 'Perfil fixo para manter a identidade da voz.';
    } else {
      $('#catalog-status').textContent = 'OFFLINE';
      $('#profile-hint').textContent = catalog.error || 'Abra o VoiceStudio local para carregar motores e perfis.';
    }
    if (!catalog.models.length) engine.add(new Option('Nenhum motor disponível', ''));
    if (!catalog.voices.length) profile.add(new Option('Nenhum perfil disponível', ''));
  } catch (error) {
    $('#catalog-status').textContent = 'OFFLINE';
    $('#profile-hint').textContent = error.message;
  }
}

$('#save-button').addEventListener('click', async () => {
  const button = $('#save-button');
  button.disabled = true;
  const message = $('#settings-message');
  message.className = 'settings-message';
  try {
    const result = await api('/api/voice/settings', { method: 'POST', body: JSON.stringify(selectedSettings()) });
    message.classList.add('success');
    message.textContent = `◇ ${result.message}`;
    notify(result.message);
  } catch (error) {
    message.classList.add('error');
    message.textContent = `◇ ${error.message}`;
    notify(error.message);
  } finally {
    button.disabled = false;
  }
});

$('#preview-button').addEventListener('click', async () => {
  const button = $('#preview-button');
  button.disabled = true;
  const state = $('#preview-state');
  state.textContent = 'GERANDO PRÉVIA…';
  $('#preview-wave').classList.remove('playing');
  $('#identity-sphere').dataset.sphereState = 'ocioso';
  try {
    const blob = await api('/api/voice/preview', { method: 'POST', body: JSON.stringify(selectedSettings()) });
    if (previewAudio) {
      previewAudio.pause();
      URL.revokeObjectURL(previewAudio.src);
    }
    previewAudio = new Audio(URL.createObjectURL(blob));
    previewAudio.onplay = () => {
      $('#preview-wave').classList.add('playing');
      $('#identity-sphere').dataset.sphereState = 'falando';
      state.textContent = 'REPRODUZINDO PRÉVIA';
    };
    previewAudio.onended = () => {
      $('#preview-wave').classList.remove('playing');
      $('#identity-sphere').dataset.sphereState = 'ocioso';
      state.textContent = 'PERFIL PRONTO';
    };
    previewAudio.onerror = () => {
      $('#preview-wave').classList.remove('playing');
      $('#identity-sphere').dataset.sphereState = 'ocioso';
      state.textContent = 'FALHA NA REPRODUÇÃO';
    };
    await previewAudio.play();
  } catch (error) {
    $('#preview-wave').classList.remove('playing');
    $('#identity-sphere').dataset.sphereState = 'ocioso';
    state.textContent = 'PRÉVIA INDISPONÍVEL';
    notify(error.message);
  }
  finally {
    button.disabled = false;
  }
});

// Clock and application startup
function tick() {
  $('#clock').textContent = new Date().toLocaleTimeString('pt-BR', { hour12: false });
}

function startApplication() {
  tick();
  setInterval(tick, 1000);

  refreshStatus();
  setInterval(refreshStatus, 3000);

  refreshVoiceState();
  setInterval(refreshVoiceState, 220);

  const requestedTab = location.hash.slice(1);
  setTab(['cli', 'voice', 'settings', 'memory', 'map'].includes(requestedTab) ? requestedTab : 'memory');
}

startApplication();

iniciarMalhaLiquida($('#voice-sphere'));
iniciarMalhaLiquida($('#cli-sphere'));
iniciarMalhaLiquida($('#identity-sphere'));
iniciarMalhaLiquida($('#memory-sphere'));


