/* Renderização da esfera animada do Alfred. */

function iniciarMalhaLiquida(canvas) {
  const imagem = new Image();
  imagem.src = '/ui/alfred-sphere.png?v=2';
  imagem.onload = () => {
    const fonte = document.createElement('canvas');
    fonte.width = imagem.naturalWidth;
    fonte.height = imagem.naturalHeight;
    const origem = fonte.getContext('2d', { willReadFrequently: true });
    origem.drawImage(imagem, 0, 0);
    const { data, width, height } = origem.getImageData(0, 0, fonte.width, fonte.height);
    const pontos = [];
    let seme = 9317;
    const aleatorio = () => {
      seme = (seme * 1664525 + 1013904223) >>> 0;
      return seme / 4294967296;
    };

    const quantidade = Math.max(1000, Number(canvas.dataset.spherePoints) || 11000);
    const anguloDourado = Math.PI * (3 - Math.sqrt(5));
    for (let indice = 0; indice < quantidade; indice++) {
      const y = 1 - 2 * (indice + 0.5) / quantidade;
      const raio = Math.sqrt(1 - y * y);
      const angulo = indice * anguloDourado;
      const x = Math.cos(angulo) * raio;
      const z = Math.sin(angulo) * raio;
      pontos.push({ x, y, z, size: 0.55 + aleatorio() * 0.7, phase: aleatorio() * Math.PI * 2 });
    }

    const contexto = canvas.getContext('2d', { alpha: true });
    let largura = 0;
    let altura = 0;
    let dpr = 1;
    let ultimoFrame = 0;
    let intensidadeMovimento = 0;
    let intensidadeFala = 0;
    let tempoFluxo = 0;
    let rotacao = 0;
    const ajustar = () => {
      const caixa = canvas.getBoundingClientRect();
      if (!caixa.width || !caixa.height) return;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      largura = caixa.width;
      altura = caixa.height;
      canvas.width = Math.round(largura * dpr);
      canvas.height = Math.round(altura * dpr);
      contexto.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    new ResizeObserver(ajustar).observe(canvas);
    ajustar();

    const desenhar = (agora) => {
      requestAnimationFrame(desenhar);
      if (!largura || !altura) { ajustar(); return; }
      const estadoEsfera = canvas.dataset.sphereState;
      const indisponivel = ['erro', 'indisponivel', 'offline'].includes(estadoEsfera);
      const falando = estadoEsfera === 'falando' || indisponivel;
      const ativo = falando || estadoEsfera === 'pensando';
      const intervalo = ultimoFrame ? Math.min(64, agora - ultimoFrame) : 16;
      ultimoFrame = agora;
      const alvoMovimento = ativo ? 1 : 0;
      const transicaoMovimento = alvoMovimento > intensidadeMovimento ? 360 : 620;
      intensidadeMovimento += (alvoMovimento - intensidadeMovimento) * (1 - Math.exp(-intervalo / transicaoMovimento));
      const transicaoFala = falando ? 300 : 520;
      intensidadeFala += ((falando ? 1 : 0) - intensidadeFala) * (1 - Math.exp(-intervalo / transicaoFala));
      tempoFluxo += intervalo * (0.00072 + intensidadeMovimento * 0.00073);
      rotacao += intervalo * (0.00022 + intensidadeMovimento * 0.00012);
      const salto = 1 + Math.sin(agora * 0.0048) * 0.018 * intensidadeFala;
      const escala = Math.min(largura, altura) * 0.38 * salto;
      const centroX = largura / 2;
      const centroY = altura / 2;
      const angulo = rotacao;
      const c = Math.cos(angulo);
      const s = Math.sin(angulo);
      const inclinacao = Math.sin(agora * 0.00013) * 0.24 + 0.12;
      const ci = Math.cos(inclinacao);
      const si = Math.sin(inclinacao);
      const tempo = tempoFluxo;
      const deformacaoLateral = 0.032 + intensidadeMovimento * 0.02;
      const deformacaoProfundidade = 0.2 + intensidadeMovimento * 0.1;
      const camadas = desenhar.camadas || (desenhar.camadas = Array.from({ length: 12 }, () => []));
      camadas.forEach((camada) => { camada.length = 0; });
      contexto.clearRect(0, 0, largura, altura);

      for (const ponto of pontos) {
        const fluxoA = Math.sin(ponto.y * 4 + tempo + ponto.phase * 0.18);
        const fluxoB = Math.cos(ponto.x * 4 - tempo * 0.82 + ponto.phase * 0.2);
        const redemoinho = Math.sin(ponto.x * 3 + ponto.y * 3 + tempo * 0.55 + ponto.phase) * 0.32;
        const xOndulado = ponto.x + (fluxoA + redemoinho) * deformacaoLateral;
        const yOndulado = ponto.y + (fluxoB - redemoinho) * deformacaoLateral;
        const zOndulado = ponto.z + (redemoinho + fluxoA * 0.35) * deformacaoProfundidade;
        const xGirado = xOndulado * c + zOndulado * s;
        const zGirado = -xOndulado * s + zOndulado * c;
        const yGirado = yOndulado * ci - zGirado * si;
        const profundidade = yOndulado * si + zGirado * ci;
        const perspectiva = 2.8 / (2.8 - profundidade * 0.7);
        const projetadoX = xGirado * perspectiva;
        const projetadoY = yGirado * perspectiva;
        const x = projetadoX * escala;
        const y = projetadoY * escala;
        const pulsacao = 0.88 + Math.sin(agora * (0.0035 + intensidadeFala * 0.0025) + ponto.phase) * (0.05 + intensidadeFala * 0.12);
        const texturaX = Math.max(0, Math.min(width - 1, Math.floor((projetadoX * 0.5 + 0.5) * width)));
        const texturaY = Math.max(0, Math.min(height - 1, Math.floor((projetadoY * 0.5 + 0.5) * height)));
        const texturaImagem = (data[(texturaY * width + texturaX) * 4 + 3] / 255) ** 1.6;
        const borda = Math.max(0, Math.min(1, (Math.hypot(projetadoX, projetadoY) - 0.5) / 0.42));
        const textura = Math.max(texturaImagem, borda * 0.58);
        const iluminacao = 0.68 + Math.max(0, profundidade) * 0.32;
        const opacidade = Math.min(1, (0.25 + textura * 0.75) * iluminacao * pulsacao * (1 + intensidadeFala * 0.1));
        const camada = Math.min(11, Math.floor(opacidade * 12));
        camadas[camada].push(x, y, ponto.size * (0.6 + textura * 0.8) * (profundidade > 0 ? 1 : 0.76));
      }
      contexto.fillStyle = indisponivel ? '#ff344f' : '#fff';
      for (let camada = 0; camada < camadas.length; camada++) {
        const pontosCamada = camadas[camada];
        if (!pontosCamada.length) continue;
        contexto.globalAlpha = (camada + 0.5) / 12;
        contexto.beginPath();
        for (let indice = 0; indice < pontosCamada.length; indice += 3) {
          contexto.moveTo(centroX + pontosCamada[indice] + pontosCamada[indice + 2], centroY + pontosCamada[indice + 1]);
          contexto.arc(centroX + pontosCamada[indice], centroY + pontosCamada[indice + 1], pontosCamada[indice + 2], 0, Math.PI * 2);
        }
        contexto.fill();
      }
      contexto.globalAlpha = 1;
    };
    requestAnimationFrame(desenhar);
  };
  imagem.onerror = () => { canvas.dataset.sphereState = 'indisponivel'; };
}
