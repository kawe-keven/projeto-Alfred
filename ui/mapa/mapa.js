(() => {
  const el = (seletor) => document.querySelector(seletor);
  const lista = el('#map-place-list');
  const filtroButtons = [...document.querySelectorAll('[data-map-filter]')];
  const markers = new Map();
  const estado = {
    active: false,
    started: false,
    loading: false,
    map: null,
    config: null,
    voice: false,
    light: false,
    threeD: true,
    silhouettes: true,
    satellite: false,
    adding: false,
    moving: null,
    editing: null,
    coordinates: null,
    selected: null,
    filter: 'TODOS',
    places: [],
    startedAt: 0,
    loadMs: null,
    renderedFrames: 0,
  };

  function mensagem(titulo, texto) {
    el('#map-placeholder-title').textContent = titulo;
    el('#map-placeholder-message').textContent = texto;
    el('#map-placeholder').hidden = false;
  }

  function status(texto, alerta = false) {
    el('#map-status').textContent = texto;
    el('#map-status-dot').classList.toggle('map-status-alert', alerta);
  }

  async function respostaJson(resposta) {
    const tipo = resposta.headers.get('content-type') || '';
    if (!tipo.toLowerCase().includes('application/json')) {
      throw new Error('O painel em execução não reconheceu esta rota do mapa. Reinicie o Alfred para carregar a versão atualizada.');
    }
    try {
      return await resposta.json();
    } catch {
      throw new Error('O painel retornou uma resposta inválida para o mapa. Reinicie o Alfred e tente novamente.');
    }
  }

  async function carregarConfig() {
    const resposta = await fetch('/api/mapa/config', { headers: { Accept: 'application/json' } });
    const config = await respostaJson(resposta);
    if (!resposta.ok) throw new Error(config.error || 'Não foi possível carregar a configuração local do mapa.');
    if (!config.available) {
      mensagem('Mapa offline não preparado', config.message || 'Consulte a seção Mapa do README para gerar a base local.');
      status('BASE LOCAL AUSENTE', true);
      return null;
    }
    return config;
  }

  function carregarMapLibre() {
    if (!window.maplibregl) {
      mensagem('Runtime local não encontrado', 'Execute scripts/vendorizar_mapa.ps1 para preparar os arquivos locais do mapa.');
      status('RUNTIME LOCAL AUSENTE', true);
      return false;
    }
    return true;
  }

  function aplicarModoLeve() {
    const mapa = estado.map;
    const toggle3d = el('#map-view-toggle');
    toggle3d.disabled = estado.light;
    if (!mapa || !mapa.getLayer('edificios') || !mapa.getLayer('edificios-planta')) return;
    mapa.setLayoutProperty('edificios', 'visibility', estado.light ? 'none' : 'visible');
    if (mapa.getLayer('edificios-contorno')) mapa.setLayoutProperty('edificios-contorno', 'visibility', estado.silhouettes ? 'visible' : 'none');
    mapa.setLayoutProperty('edificios-planta', 'visibility', 'visible');
    mapa.setPaintProperty('edificios-planta', 'fill-opacity', estado.satellite ? 0.32 : 0.88);
    if (estado.threeD && !estado.light && mapa.getZoom() < 11) mapa.setZoom(11);
    mapa.setPitch(estado.light || !estado.threeD ? 0 : estado.config.pitch);
    if (mapa.getLayer('imagem-satelite')) {
      mapa.setLayoutProperty('imagem-satelite', 'visibility', estado.satellite ? 'visible' : 'none');
      for (const id of ['agua', 'parques', 'ruas']) {
        if (mapa.getLayer(id)) mapa.setLayoutProperty(id, 'visibility', estado.satellite ? 'none' : 'visible');
      }
    }
    el('#map-light-toggle').checked = estado.light;
    toggle3d.textContent = estado.threeD && !estado.light ? '3D' : '2D';
    toggle3d.setAttribute('aria-pressed', String(estado.threeD && !estado.light));
    const satelliteToggle = el('#map-satellite-toggle');
    satelliteToggle.title = estado.config.satelliteAvailable
      ? 'Alternar imagem de satélite'
      : 'Configure o provedor de imagens em config.yaml';
    satelliteToggle.classList.toggle('active', estado.satellite);
    satelliteToggle.setAttribute('aria-pressed', String(estado.satellite));
  }

  function renderPlaceList() {
    lista.replaceChildren();
    const places = estado.places.filter((place) => estado.filter === 'TODOS' || place.categoria === estado.filter);
    el('#map-place-count').textContent = String(estado.places.length);
    if (!places.length) {
      const vazio = document.createElement('li');
      vazio.className = 'map-place-empty';
      vazio.textContent = estado.places.length ? 'Nenhum lugar nesta categoria.' : 'Os lugares salvos aparecerão aqui.';
      lista.append(vazio);
    }
    for (const place of places) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'map-place-item';
      button.setAttribute('aria-current', String(estado.selected?.id === place.id));
      const code = document.createElement('span');
      code.className = 'map-place-code';
      code.textContent = place.codigo || place.code || place.categoria;
      const name = document.createElement('span');
      name.className = 'map-place-name';
      name.textContent = place.nome;
      button.append(code, name);
      button.addEventListener('click', () => selecionar(place, true));
      item.append(button);
      lista.append(item);
    }
  }

  function marcador(place) {
    const codigo = place.codigo || place.code || place.categoria;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'map-marker';
    button.title = place.nome;
    button.setAttribute('aria-label', `${codigo}: ${place.nome}`);
    const square = document.createElement('span');
    square.className = 'map-marker-square';
    square.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.className = 'map-marker-label';
    label.textContent = codigo;
    button.append(square, label);
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      selecionar(place, false);
    });
    return button;
  }

  function sincronizarMarkers() {
    for (const marker of markers.values()) marker.remove();
    markers.clear();
    if (!estado.map) return;
    for (const place of estado.places) {
      if (!Number.isFinite(Number(place.lat)) || !Number.isFinite(Number(place.lon))) continue;
      const marker = new window.maplibregl.Marker({ element: marcador(place), anchor: 'bottom' })
        .setLngLat([Number(place.lon), Number(place.lat)])
        .addTo(estado.map);
      markers.set(place.id, marker);
    }
  }

  function selecionar(place, centralizar) {
    estado.selected = place;
    el('#map-place-card').hidden = false;
    el('#map-card-code').textContent = place.codigo || place.code || place.categoria;
    el('#map-card-name').textContent = place.nome;
    el('#map-card-category').textContent = `${place.categoria} · ${({ CAS: 'CASA', FAC: 'FACULDADE', TRB: 'TRABALHO', LOC: 'OUTRO' })[place.categoria] || 'LUGAR'}`;
    renderPlaceList();
    if (centralizar && estado.map) {
      estado.map.jumpTo({ center: [Number(place.lon), Number(place.lat)], zoom: Math.max(estado.map.getZoom(), 14), pitch: estado.light ? 0 : estado.map.getPitch() });
    }
  }

  function mostrarFormulario({ lugar = null, coordenadas = null } = {}) {
    estado.editing = lugar;
    estado.coordinates = coordenadas;
    el('#map-place-card').hidden = true;
    el('#map-place-form').hidden = false;
    el('#map-form-title').textContent = lugar ? `EDITAR ${lugar.codigo || lugar.categoria}` : 'NOVO LUGAR';
    el('#map-place-name').value = lugar?.nome || '';
    el('#map-place-category').value = lugar?.categoria || 'LOC';
    el('#map-place-category').disabled = Boolean(lugar);
    el('#map-place-name').focus();
  }

  function fecharFormulario() {
    estado.editing = null;
    estado.coordinates = null;
    estado.adding = false;
    estado.moving = null;
    el('#map-place-form').hidden = true;
    el('#map-place-category').disabled = false;
    status(estado.map ? 'MAPA SOB DEMANDA' : 'MAPA INDISPONÍVEL', !estado.map);
  }

  async function pedirJson(url, opcoes = {}) {
    const resposta = await fetch(url, {
      headers: { Accept: 'application/json', ...(opcoes.body ? { 'Content-Type': 'application/json' } : {}) },
      ...opcoes,
    });
    const dados = await respostaJson(resposta);
    if (!resposta.ok) throw new Error(dados.error || dados.message || 'Não foi possível concluir a ação.');
    return dados;
  }

  async function carregarLugares() {
    try {
      const dados = await pedirJson('/api/mapa/lugares');
      estado.places = Array.isArray(dados) ? dados : (dados.lugares || dados.places || []);
      el('#map-session-notice').hidden = !(dados.sessionOnly || dados.persistent === false || ['sessao', 'memoria'].includes(dados.modo));
      renderPlaceList();
      sincronizarMarkers();
    } catch (error) {
      estado.places = [];
      renderPlaceList();
      status('LUGARES INDISPONÍVEIS', true);
      if (!estado.map) el('#map-place-list').querySelector('.map-place-empty').textContent = error.message;
    }
  }

  async function inicializar() {
    if (estado.started || estado.loading || !estado.active) return;
    estado.loading = true;
    estado.startedAt = performance.now();
    estado.renderedFrames = 0;
    try {
      const config = await carregarConfig();
      if (!config || !estado.active) return;
      estado.config = config;
      el('#map-attribution').textContent = config.attribution || '© OpenStreetMap contributors · Fonte local';
      if (config.satelliteAttribution) el('#map-attribution').textContent += ` · ${config.satelliteAttribution}`;
      if (!carregarMapLibre()) return;
      const worker = '/ui/vendor/maplibre-gl/maplibre-gl-csp-worker.js';
      if (typeof window.maplibregl.setWorkerUrl === 'function') window.maplibregl.setWorkerUrl(worker);
      estado.map = new window.maplibregl.Map({
        container: 'map-canvas',
        style: '/api/mapa/estilo',
        center: config.center,
        zoom: config.zoom,
        pitch: config.pitch,
        maxPitch: config.maxPitch,
        antialias: config.antialias,
        attributionControl: false,
        dragRotate: true,
        renderWorldCopies: true,
      });
      estado.map.on('load', () => {
        if (estado.map.getLayer('edificios-contorno')) estado.map.moveLayer('edificios-contorno');
        estado.started = true;
        estado.loadMs = performance.now() - estado.startedAt;
        el('#map-placeholder').hidden = true;
        status(`MAPA PRONTO · ${Math.round(estado.loadMs)} MS`);
        aplicarModoLeve();
        sincronizarMarkers();
      });
      estado.map.on('render', () => { estado.renderedFrames += 1; });
      estado.map.on('zoomend', () => {
        if (estado.threeD && !estado.light && estado.map.getZoom() < 11) estado.map.setZoom(11);
      });
      estado.map.on('idle', () => {
        if (estado.loadMs !== null && estado.active) {
          status(`MAPA PRONTO · ${Math.round(estado.loadMs)} MS · ${estado.renderedFrames} QUADROS`);
        }
      });
      estado.map.on('error', (event) => {
        if (!estado.started) {
          const detalhe = String(event?.error?.message || event?.message || 'Falha desconhecida ao iniciar o mapa.')
            .replace(/https?:\/\/\S+/g, '[endereço local]')
            .slice(0, 220);
          mensagem('Não foi possível carregar a base local', `Falha do mapa: ${detalhe}`);
          status('ERRO NA BASE LOCAL', true);
        }
      });
      estado.map.on('click', (event) => {
        if (estado.moving) {
          const lugar = estado.moving;
          estado.moving = null;
          const body = { lat: event.lngLat.lat, lon: event.lngLat.lng };
          pedirJson(`/api/mapa/lugares/${encodeURIComponent(lugar.id)}`, { method: 'PATCH', body: JSON.stringify(body) })
            .then(carregarLugares)
            .catch((error) => notify(error.message));
          status('CONFIRME A NOVA POSIÇÃO');
          return;
        }
        if (estado.adding) {
          estado.adding = false;
          mostrarFormulario({ coordenadas: { lat: event.lngLat.lat, lon: event.lngLat.lng } });
          status('NOVO LUGAR · CONFIRME PARA SALVAR');
        }
      });
      requestAnimationFrame(() => estado.map?.resize());
    } catch (error) {
      mensagem('Mapa local indisponível', error.message || 'Não foi possível abrir o mapa local.');
      status('MAPA INDISPONÍVEL', true);
    } finally {
      estado.loading = false;
    }
  }

  async function salvarLugar(event) {
    event.preventDefault();
    const nome = el('#map-place-name').value.trim();
    if (!nome) return;
    const botao = el('#map-save-place');
    botao.disabled = true;
    try {
      if (estado.editing) {
        await pedirJson(`/api/mapa/lugares/${encodeURIComponent(estado.editing.id)}`, {
          method: 'PATCH', body: JSON.stringify({ nome }),
        });
      } else if (estado.coordinates) {
        await pedirJson('/api/mapa/lugares', {
          method: 'POST', body: JSON.stringify({ nome, categoria: el('#map-place-category').value, ...estado.coordinates }),
        });
      }
      fecharFormulario();
      await carregarLugares();
      status('LUGAR SALVO');
    } catch (error) {
      notify(error.message);
      status('CONFIRMAÇÃO NECESSÁRIA', true);
    } finally {
      botao.disabled = false;
    }
  }

  function ligarControles() {
    el('#map-add-place').addEventListener('click', () => {
      if (!estado.map) {
        notify('Prepare a base offline antes de adicionar um lugar pelo mapa.');
        return;
      }
      estado.adding = true;
      estado.selected = null;
      el('#map-place-card').hidden = true;
      el('#map-place-form').hidden = true;
      status('CLIQUE NO MAPA PARA MARCAR O LUGAR');
    });
    el('#map-cancel-place').addEventListener('click', fecharFormulario);
    el('#map-place-form').addEventListener('submit', salvarLugar);
    el('#map-zoom-in').addEventListener('click', () => estado.map?.zoomIn());
    el('#map-zoom-out').addEventListener('click', () => estado.map?.zoomOut());
    document.querySelectorAll('[data-map-city]').forEach((button) => button.addEventListener('click', () => {
      if (!estado.map) return;
      const centros = {
        aracaju: [-37.0731, -10.9472],
        laranjeiras: [-37.1658, -10.804],
      };
      const centro = centros[button.dataset.mapCity];
      if (!centro) return;
      estado.map.flyTo({ center: centro, zoom: 15, pitch: estado.light ? 0 : estado.config.pitch, bearing: 0, duration: 900 });
    }));
    el('#map-reset').addEventListener('click', () => {
      if (!estado.map || !estado.config) return;
      estado.threeD = true;
      estado.map.jumpTo({ center: estado.config.center, zoom: estado.config.zoom, pitch: estado.light ? 0 : estado.config.pitch, bearing: 0 });
      aplicarModoLeve();
    });
    el('#map-view-toggle').addEventListener('click', () => {
      if (estado.light) return;
      estado.threeD = !estado.threeD;
      aplicarModoLeve();
    });
    el('#map-outline-toggle').addEventListener('click', () => {
      estado.silhouettes = !estado.silhouettes;
      aplicarModoLeve();
      const button = el('#map-outline-toggle');
      button.classList.toggle('active', estado.silhouettes);
      button.setAttribute('aria-pressed', String(estado.silhouettes));
      status(estado.silhouettes ? 'CONTORNOS INDIVIDUAIS ATIVOS · ZOOM ALTO' : 'CONTORNOS INDIVIDUAIS DESATIVADOS');
    });
    el('#map-satellite-toggle').addEventListener('click', () => {
      if (!estado.config?.satelliteAvailable || !estado.map) {
        notify('Configure ALFRED_MAPA_SATELITE_URL e reinicie o Alfred para ativar imagens de satélite.');
        return;
      }
      estado.satellite = !estado.satellite;
      aplicarModoLeve();
      status(estado.satellite ? 'IMAGEM DE SATÉLITE · EDIFÍCIOS 3D' : 'MAPA VETORIAL · MODO 3D');
    });
    el('#map-light-toggle').addEventListener('change', (event) => {
      estado.light = event.currentTarget.checked;
      if (estado.light) estado.threeD = false;
      aplicarModoLeve();
    });
    filtroButtons.forEach((button) => button.addEventListener('click', () => {
      estado.filter = button.dataset.mapFilter;
      filtroButtons.forEach((filtro) => {
        const selecionado = filtro === button;
        filtro.classList.toggle('active', selecionado);
        filtro.setAttribute('aria-pressed', String(selecionado));
      });
      renderPlaceList();
    }));
    el('#map-edit-place').addEventListener('click', () => {
      if (estado.selected) mostrarFormulario({ lugar: estado.selected });
    });
    el('#map-move-place').addEventListener('click', () => {
      if (!estado.selected || !estado.map) return;
      estado.moving = estado.selected;
      status('CLIQUE NO MAPA PARA MOVER O LUGAR');
    });
    el('#map-remove-place').addEventListener('click', async () => {
      if (!estado.selected) return;
      try {
        await pedirJson(`/api/mapa/lugares/${encodeURIComponent(estado.selected.id)}`, { method: 'DELETE' });
        estado.selected = null;
        el('#map-place-card').hidden = true;
        await carregarLugares();
        status('LUGAR REMOVIDO');
      } catch (error) {
        notify(error.message);
        status('CONFIRMAÇÃO NECESSÁRIA', true);
      }
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) estado.map?.stop();
      else if (estado.active && estado.map) requestAnimationFrame(() => estado.map?.resize());
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && (estado.adding || estado.moving)) {
        estado.adding = false;
        estado.moving = null;
        status('MAPA SOB DEMANDA');
      }
    });
  }

  ligarControles();
  window.alfredMapa = {
    setActive(active) {
      estado.active = active;
      if (active) {
        carregarLugares();
        if (!estado.started) inicializar();
        else requestAnimationFrame(() => estado.map?.resize());
      } else estado.map?.stop();
    },
    setVoiceActive(active) {
      estado.voice = active;
      el('#map-voice-hint').hidden = !active;
    },
  };
})();
