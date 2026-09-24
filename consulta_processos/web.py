"""Tela no navegador para quem não usa linha de comando.

Sobe um servidor pequeno na própria máquina e abre a página. Nada sai para fora:
as consultas continuam indo direto do seu computador às fontes do CNJ.

    consulta-processos web

Sem dependência nenhuma além da biblioteca padrão do Python — a página é um
arquivo só, com o estilo embutido, para funcionar mesmo sem internet boa.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .api import buscar_por_oab, consultar_processo, publicacoes_por_oab
from .config import CHAVE_PUBLICA_DATAJUD, Config, carregar_env
from .erros import ConsultaError

logger = logging.getLogger(__name__)

# O .env em uso — a tela grava nele o que você preencher
ARQUIVO_ENV: Path | None = None

PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Consulta de Processos</title>
<style>
  :root {
    --fundo: #f6f7f9; --papel: #ffffff; --texto: #1c2430; --suave: #6b7683;
    --linha: #e3e7ec; --destaque: #1f4f82; --destaque-claro: #eaf1f9;
    --erro: #b3261e; --ok: #1e7a4d;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --fundo: #14181d; --papel: #1b2027; --texto: #e6eaef; --suave: #97a1ad;
      --linha: #2a313a; --destaque: #6aa4e0; --destaque-claro: #1e2833;
      --erro: #f2a5a0; --ok: #7fd0a6;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--fundo); color: var(--texto);
    font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  header {
    background: var(--papel); border-bottom: 1px solid var(--linha);
    padding: 18px 16px;
  }
  .limite { max-width: 880px; margin: 0 auto; }
  h1 { font-size: 19px; margin: 0; font-weight: 650; letter-spacing: -0.01em; }
  header p { margin: 4px 0 0; color: var(--suave); font-size: 13px; }
  main { padding: 22px 16px 60px; }

  .abas { display: flex; gap: 4px; margin-bottom: 18px; flex-wrap: wrap; }
  .aba {
    border: 1px solid var(--linha); background: var(--papel); color: var(--suave);
    padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px;
    font-family: inherit;
  }
  .aba[aria-selected="true"] {
    background: var(--destaque); border-color: var(--destaque); color: #fff; font-weight: 600;
  }

  .caixa {
    background: var(--papel); border: 1px solid var(--linha);
    border-radius: 12px; padding: 20px; margin-bottom: 18px;
  }
  label { display: block; font-size: 13px; color: var(--suave); margin-bottom: 6px; }
  input, select {
    width: 100%; padding: 11px 12px; font-size: 15px; font-family: inherit;
    border: 1px solid var(--linha); border-radius: 8px;
    background: var(--fundo); color: var(--texto);
  }
  input:focus, select:focus { outline: 2px solid var(--destaque); outline-offset: -1px; }
  .linha { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
  .linha > div { flex: 1 1 180px; }
  button.acao {
    background: var(--destaque); color: #fff; border: 0; border-radius: 8px;
    padding: 11px 24px; font-size: 15px; font-weight: 600; cursor: pointer;
    font-family: inherit; white-space: nowrap;
  }
  button.acao:disabled { opacity: .6; cursor: default; }

  .aviso { font-size: 13px; color: var(--suave); margin-top: 12px; }
  .erro { color: var(--erro); }
  .carregando { display: flex; align-items: center; gap: 10px; color: var(--suave); font-size: 14px; }
  .bolinha {
    width: 14px; height: 14px; border: 2px solid var(--linha);
    border-top-color: var(--destaque); border-radius: 50%;
    animation: gira .8s linear infinite;
  }
  @keyframes gira { to { transform: rotate(360deg); } }

  .cabecalho h2 { margin: 0 0 2px; font-size: 17px; letter-spacing: -0.01em; }
  .cabecalho .numero { font-family: ui-monospace, Consolas, monospace; font-size: 14px; color: var(--suave); }
  .etiquetas { display: flex; gap: 6px; flex-wrap: wrap; margin: 12px 0 0; }
  .etiqueta {
    background: var(--destaque-claro); color: var(--destaque);
    padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600;
  }
  dl.campos { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 16px 0 0; }
  dl.campos dt { color: var(--suave); font-size: 13px; }
  dl.campos dd { margin: 0; font-size: 14px; }

  h3.secao {
    font-size: 13px; text-transform: uppercase; letter-spacing: .06em;
    color: var(--suave); margin: 0 0 12px; font-weight: 650;
  }
  ul.lista { list-style: none; margin: 0; padding: 0; }
  ul.lista li { padding: 10px 0; border-bottom: 1px solid var(--linha); font-size: 14px; }
  ul.lista li:last-child { border-bottom: 0; }
  .data { color: var(--suave); font-size: 13px; font-family: ui-monospace, Consolas, monospace; }
  .parte-polo { color: var(--suave); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  details summary { cursor: pointer; color: var(--destaque); font-size: 13px; margin-top: 6px; }
  details p {
    white-space: pre-wrap; font-size: 13px; color: var(--texto);
    background: var(--fundo); padding: 12px; border-radius: 8px; margin: 8px 0 0;
  }
  .vazio { color: var(--suave); font-size: 14px; }
  @media (max-width: 560px) {
    dl.campos { grid-template-columns: 1fr; gap: 2px 0; }
    dl.campos dd { margin-bottom: 8px; }
  }
</style>
</head>
<body>
<header>
  <div class="limite">
    <h1>Consulta de Processos</h1>
    <p>Dados públicos do CNJ &mdash; Datajud e diário eletrônico</p>
  </div>
</header>

<main class="limite">
  <div class="abas" role="tablist">
    <button class="aba" role="tab" aria-selected="true"  data-aba="processo">Processo</button>
    <button class="aba" role="tab" aria-selected="false" data-aba="oab">Processos do advogado</button>
    <button class="aba" role="tab" aria-selected="false" data-aba="diario">Diário</button>
  </div>

  <form class="caixa" id="f-processo">
    <div class="linha">
      <div style="flex:2 1 320px;">
        <label for="numero">Número do processo</label>
        <input id="numero" name="numero" placeholder="0000000-00.0000.0.00.0000"
               autocomplete="off" required>
      </div>
      <button class="acao" type="submit">Consultar</button>
    </div>
    <p class="aviso">Pode digitar com ou sem pontuação. A consulta ao Datajud costuma
      levar de 30 a 60 segundos.</p>
  </form>

  <form class="caixa" id="f-oab" hidden>
    <div class="linha">
      <div><label for="oab-numero">Número da OAB</label>
        <input id="oab-numero" placeholder="123456" autocomplete="off" required></div>
      <div style="flex:0 1 110px;"><label for="oab-uf">UF</label>
        <input id="oab-uf" placeholder="MG" maxlength="2" autocomplete="off" required></div>
      <div><label for="oab-tribunal">Tribunal (opcional)</label>
        <input id="oab-tribunal" placeholder="TJMG" autocomplete="off"></div>
      <div style="flex:0 1 160px;"><label for="oab-dias">Período</label>
        <select id="oab-dias">
          <option value="30">Últimos 30 dias</option>
          <option value="60">Últimos 60 dias</option>
          <option value="90">Últimos 90 dias</option>
          <option value="180">Últimos 180 dias</option>
        </select></div>
      <button class="acao" type="submit">Buscar</button>
    </div>
    <p class="aviso">Traz os processos em que essa OAB foi publicada no diário durante o
      período &mdash; não a carteira inteira. A API pública do Datajud não informa os
      advogados do processo, então o diário é o único caminho.</p>
  </form>

  <form class="caixa" id="f-diario" hidden>
    <div class="linha">
      <div><label for="d-numero">Número da OAB</label>
        <input id="d-numero" placeholder="123456" autocomplete="off" required></div>
      <div style="flex:0 1 110px;"><label for="d-uf">UF</label>
        <input id="d-uf" placeholder="MG" maxlength="2" autocomplete="off" required></div>
      <div style="flex:0 1 150px;"><label for="d-dias">Período</label>
        <select id="d-dias">
          <option value="7">Últimos 7 dias</option>
          <option value="15">Últimos 15 dias</option>
          <option value="30">Últimos 30 dias</option>
        </select></div>
      <button class="acao" type="submit">Buscar</button>
    </div>
    <p class="aviso">Publicações do diário eletrônico. Esta consulta não usa o Datajud
      e costuma responder em segundos.</p>
  </form>

  <div id="saida"></div>

  <details class="caixa" id="config" style="margin-top:26px;">
    <summary style="cursor:pointer; font-size:14px; font-weight:600;">Configuração</summary>
    <div style="margin-top:16px;">
      <div style="margin-bottom:14px;">
        <label for="cfg-chave">Chave da API do Datajud</label>
        <input id="cfg-chave" type="password" autocomplete="off"
               placeholder="deixe em branco para usar a chave pública do CNJ">
        <p class="aviso" id="cfg-chave-estado"></p>
      </div>
      <div style="margin-bottom:14px;">
        <label for="cfg-proxies">Proxies (um por linha)</label>
        <textarea id="cfg-proxies" rows="3" spellcheck="false"
          style="width:100%; padding:11px 12px; font-size:14px; font-family:ui-monospace,Consolas,monospace;
                 border:1px solid var(--linha); border-radius:8px; background:var(--fundo); color:var(--texto);"
          placeholder="http://usuario:senha@host:porta&#10;socks5h://usuario:senha@host:porta"></textarea>
        <p class="aviso">Opcional. O diário do CNJ recusa acessos de fora do Brasil e limita
          consultas por IP &mdash; é para esses casos. Rodando do Brasil, deixe em branco.</p>
      </div>
      <button class="acao" type="button" id="cfg-salvar">Salvar</button>
      <span class="aviso" id="cfg-recado" style="margin-left:10px;"></span>
    </div>
  </details>
</main>

<script>
const $ = s => document.querySelector(s);
const saida = $('#saida');
const formularios = { processo: $('#f-processo'), oab: $('#f-oab'), diario: $('#f-diario') };

document.querySelectorAll('.aba').forEach(botao => {
  botao.addEventListener('click', () => {
    document.querySelectorAll('.aba').forEach(b =>
      b.setAttribute('aria-selected', String(b === botao)));
    for (const [nome, form] of Object.entries(formularios)) form.hidden = nome !== botao.dataset.aba;
    saida.innerHTML = '';
  });
});

function escapar(t) {
  return String(t ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function dataBR(iso) {
  if (!iso) return '';
  const [a, m, d] = String(iso).slice(0, 10).split('-');
  return d ? `${d}/${m}/${a}` : '';
}

function carregando(mensagem) {
  saida.innerHTML = `<div class="caixa"><div class="carregando">
    <div class="bolinha"></div><div>${escapar(mensagem)}</div></div></div>`;
}

function mostrarErro(mensagem) {
  saida.innerHTML = `<div class="caixa"><p class="erro" style="margin:0">${escapar(mensagem)}</p></div>`;
}

async function pedir(caminho, corpo) {
  const r = await fetch(caminho, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  });
  const d = await r.json();
  if (!d.ok) throw new Error(d.erro || 'Não foi possível consultar.');
  return d.dado;
}

// ── Processo ────────────────────────────────────────────────────────────────
formularios.processo.addEventListener('submit', async e => {
  e.preventDefault();
  const numero = $('#numero').value.trim();
  if (!numero) return;
  carregando('Consultando o Datajud e o diário… isso pode levar até um minuto.');
  try {
    const p = await pedir('/api/processo', { numero });
    if (!p) { mostrarErro('Nenhuma das fontes públicas conhece esse processo ainda.'); return; }
    desenharProcesso(p);
  } catch (erro) { mostrarErro(erro.message); }
});

function desenharProcesso(p) {
  const campo = (rotulo, valor) => valor ? `<dt>${rotulo}</dt><dd>${escapar(valor)}</dd>` : '';
  const moeda = v => v == null ? '' :
    v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  const partes = (p.partes || []).map(x =>
    `<li><span class="parte-polo">${escapar(x.polo || '')}</span><br>${escapar(x.nome)}</li>`).join('');
  const advogados = (p.advogados || []).map(a => {
    const oab = a.oab_numero ? ` &middot; OAB ${escapar(a.oab_uf)} ${escapar(a.oab_numero)}` : '';
    return `<li>${escapar(a.nome)}${oab}</li>`;
  }).join('');
  const movimentos = (p.movimentacoes || []).map(m => `<li>
      <span class="data">${dataBR(m.data)}</span> &nbsp; ${escapar(m.descricao)}
      ${m.complemento ? `<br><span class="vazio">${escapar(m.complemento)}</span>` : ''}
    </li>`).join('');
  const publicacoes = (p.publicacoes || []).map(pub => `<li>
      <span class="data">${dataBR(pub.data_disponibilizacao)}</span> &nbsp;
      ${escapar(pub.tipo_comunicacao || 'Publicação')}
      ${pub.orgao ? `<br><span class="vazio">${escapar(pub.orgao)}</span>` : ''}
      ${pub.texto ? `<details><summary>ver o teor</summary><p>${escapar(pub.texto)}</p></details>` : ''}
    </li>`).join('');

  const bloco = (titulo, conteudo, vazio) => `<div class="caixa">
      <h3 class="secao">${titulo}</h3>
      ${conteudo ? `<ul class="lista">${conteudo}</ul>` : `<p class="vazio">${vazio}</p>`}
    </div>`;

  saida.innerHTML = `
    <div class="caixa cabecalho">
      <h2>${escapar(p.classe || 'Processo')}</h2>
      <div class="numero">${escapar(p.numero)}</div>
      <div class="etiquetas">
        ${(p.fontes || []).map(f => `<span class="etiqueta">${escapar(f)}</span>`).join('')}
      </div>
      <dl class="campos">
        ${campo('Tribunal', p.tribunal)}
        ${campo('Órgão julgador', p.orgao_julgador)}
        ${campo('Assunto', p.assunto)}
        ${campo('Comarca', p.comarca)}
        ${campo('Valor da causa', moeda(p.valor_causa))}
        ${campo('Ajuizamento', dataBR(p.data_ajuizamento))}
        ${campo('Última movimentação', dataBR(p.data_ultima_movimentacao))}
      </dl>
    </div>
    ${bloco('Partes', partes, 'As fontes não informaram as partes.')}
    ${bloco('Advogados', advogados, 'Nenhum advogado informado.')}
    ${bloco(`Movimentações (${(p.movimentacoes || []).length})`, movimentos, 'Sem movimentações.')}
    ${bloco(`Publicações no diário (${(p.publicacoes || []).length})`, publicacoes, 'Sem publicações no período consultado.')}`;
}

// ── Processos por OAB ───────────────────────────────────────────────────────
formularios.oab.addEventListener('submit', async e => {
  e.preventDefault();
  carregando('Consultando o diário eletrônico…');
  try {
    const lista = await pedir('/api/oab', {
      numero: $('#oab-numero').value.trim(),
      uf: $('#oab-uf').value.trim(),
      tribunal: $('#oab-tribunal').value.trim(),
      dias: Number($('#oab-dias').value),
    });
    if (!lista.length) {
      mostrarErro('Nenhuma publicação dessa inscrição no período. Tente um período maior, '
                  + 'ou confira o número e a UF.');
      return;
    }
    saida.innerHTML = `<div class="caixa">
      <h3 class="secao">${lista.length} processo(s)</h3>
      <ul class="lista">${lista.map(p => `<li>
        <span class="data">${escapar(p.numero)}</span> &nbsp; ${escapar(p.tribunal || '')}
        <br>${escapar(p.classe || '')}
        ${p.orgao_julgador ? `<br><span class="vazio">${escapar(p.orgao_julgador)}</span>` : ''}
      </li>`).join('')}</ul></div>`;
  } catch (erro) { mostrarErro(erro.message); }
});

// ── Diário por OAB ──────────────────────────────────────────────────────────
formularios.diario.addEventListener('submit', async e => {
  e.preventDefault();
  carregando('Consultando o diário eletrônico…');
  try {
    const lista = await pedir('/api/publicacoes', {
      numero: $('#d-numero').value.trim(),
      uf: $('#d-uf').value.trim(),
      dias: Number($('#d-dias').value),
    });
    if (!lista.length) { mostrarErro('Nenhuma publicação no período.'); return; }
    saida.innerHTML = `<div class="caixa">
      <h3 class="secao">${lista.length} publicação(ões)</h3>
      <ul class="lista">${lista.map(pub => `<li>
        <span class="data">${dataBR(pub.data_disponibilizacao)}</span> &nbsp;
        <span class="data">${escapar(pub.numero_processo || '')}</span>
        <br>${escapar(pub.tipo_comunicacao || '')} ${pub.orgao ? '&middot; ' + escapar(pub.orgao) : ''}
        ${pub.texto ? `<details><summary>ver o teor</summary><p>${escapar(pub.texto)}</p></details>` : ''}
      </li>`).join('')}</ul></div>`;
  } catch (erro) { mostrarErro(erro.message); }
});

// ── Configuração: chave e proxy ─────────────────────────────────────────────
function mostrarConfig(d) {
  $('#cfg-proxies').value = d.proxies || '';
  const estado = $('#cfg-chave-estado');
  if (d.chave_e_a_publica) {
    estado.textContent = 'Usando a chave pública do CNJ, que já vem embutida. '
      + 'Preencha aqui só se tiver uma chave própria.';
  } else if (d.chave_definida) {
    estado.textContent = 'Uma chave própria está configurada' + (d.arquivo ? ` (${d.arquivo})` : '') + '.';
  } else {
    estado.textContent = 'Nenhuma chave configurada.';
  }
}

fetch('/api/configuracao').then(r => r.json()).then(d => { if (d.ok) mostrarConfig(d.dado); });

$('#cfg-salvar').addEventListener('click', async () => {
  const botao = $('#cfg-salvar'), recado = $('#cfg-recado');
  botao.disabled = true; recado.textContent = 'salvando…'; recado.className = 'aviso';
  try {
    const d = await pedir('/api/configuracao', {
      datajud_api_key: $('#cfg-chave').value.trim(),
      proxies: $('#cfg-proxies').value,
    });
    $('#cfg-chave').value = '';
    recado.textContent = `Salvo em ${d.salvo_em}. `
      + (d.proxies ? `${d.proxies} proxy(s) em uso. ` : 'Sem proxy. ')
      + 'Já vale nas próximas consultas.';
    fetch('/api/configuracao').then(r => r.json()).then(x => { if (x.ok) mostrarConfig(x.dado); });
  } catch (erro) {
    recado.textContent = erro.message; recado.className = 'aviso erro';
  } finally { botao.disabled = false; }
});

$('#numero').focus();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "consulta-processos"
    config: Config

    def log_message(self, formato, *args):  # silencia o log de acesso do stdlib
        logger.debug("%s - %s", self.address_string(), formato % args)

    def _responder(self, codigo: int, corpo: bytes, tipo: str):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dado: dict, codigo: int = 200):
        self._responder(codigo, json.dumps(dado, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._responder(200, PAGINA.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/configuracao":
            cfg = self.config
            self._json({"ok": True, "dado": {
                # a chave volta mascarada: a tela só precisa saber que existe
                "chave_definida": bool(cfg.datajud_api_key),
                "chave_e_a_publica": cfg.datajud_api_key == CHAVE_PUBLICA_DATAJUD,
                "proxies": "\n".join(cfg.proxies),
                "arquivo": str(ARQUIVO_ENV) if ARQUIVO_ENV else "",
            }})
        else:
            self._responder(404, b"nao encontrado", "text/plain; charset=utf-8")

    def _salvar_configuracao(self, corpo: dict) -> dict:
        """Grava chave e proxies no .env da pasta e passa a usá-los na hora."""
        global ARQUIVO_ENV
        chave = str(corpo.get("datajud_api_key", "")).strip()
        proxies = [linha.strip() for linha in str(corpo.get("proxies", "")).splitlines()
                   if linha.strip() and not linha.strip().startswith("#")]

        destino = ARQUIVO_ENV or (Path.cwd() / ".env")
        valores = {}
        if destino.is_file():
            for linha in destino.read_text(encoding="utf-8").splitlines():
                if "=" in linha and not linha.strip().startswith("#"):
                    nome, _, valor = linha.partition("=")
                    valores[nome.strip()] = valor.strip()
        if chave:
            valores["DATAJUD_API_KEY"] = chave
        valores["CONSULTA_PROXIES"] = ",".join(proxies)
        destino.write_text(
            "# Escrito pela tela de Consulta de Processos.\n"
            + "".join(f"{nome}={valor}\n" for nome, valor in valores.items()),
            encoding="utf-8")
        ARQUIVO_ENV = destino

        # vale já nesta sessão, sem reiniciar
        if chave:
            os.environ["DATAJUD_API_KEY"] = chave
        os.environ["CONSULTA_PROXIES"] = ",".join(proxies)
        _Handler.config = Config.do_ambiente()
        return {"salvo_em": str(destino), "proxies": len(proxies),
                "chave_definida": bool(_Handler.config.datajud_api_key)}

    def do_POST(self):  # noqa: N802
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except (ValueError, TypeError):
            self._json({"ok": False, "erro": "Pedido malformado."}, 400)
            return

        try:
            if self.path == "/api/processo":
                processo = consultar_processo(str(corpo.get("numero", "")), config=self.config)
                self._json({"ok": True, "dado": processo.to_dict() if processo else None})
            elif self.path == "/api/oab":
                achados = buscar_por_oab(
                    str(corpo.get("numero", "")), str(corpo.get("uf", "")),
                    tribunal=str(corpo.get("tribunal", "")),
                    dias=max(1, min(int(corpo.get("dias") or 30), 180)), config=self.config)
                self._json({"ok": True, "dado": [p.to_dict() for p in achados]})
            elif self.path == "/api/configuracao":
                self._json({"ok": True, "dado": self._salvar_configuracao(corpo)})
            elif self.path == "/api/publicacoes":
                dias = max(1, min(int(corpo.get("dias") or 7), 90))
                hoje = date.today()
                publicacoes = publicacoes_por_oab(
                    str(corpo.get("numero", "")), str(corpo.get("uf", "")),
                    inicio=hoje - timedelta(days=dias), fim=hoje, config=self.config)
                self._json({"ok": True, "dado": [p.to_dict() for p in publicacoes]})
            else:
                self._json({"ok": False, "erro": "Endereço desconhecido."}, 404)
        except ConsultaError as e:
            # Erro esperado (número inválido, fonte fora do ar, sem chave): vira recado.
            self._json({"ok": False, "erro": str(e)})
        except Exception:  # noqa: BLE001
            logger.exception("falha ao atender %s", self.path)
            self._json({"ok": False, "erro": "Algo deu errado na consulta. "
                                             "Veja o terminal para o detalhe."}, 500)


def servir(porta: int = 8765, *, abrir: bool = True, config: Config | None = None) -> int:
    """Sobe a tela em http://localhost:<porta> e, por padrão, abre o navegador."""
    global ARQUIVO_ENV
    ARQUIVO_ENV = carregar_env() or ARQUIVO_ENV
    _Handler.config = config or Config.do_ambiente()
    endereco = f"http://localhost:{porta}"

    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), _Handler)
    except OSError as e:
        print(f"Não consegui usar a porta {porta} ({e}). "
              f"Tente outra: consulta-processos web --porta {porta + 1}")
        return 1

    print(f"Consulta de Processos aberta em {endereco}")
    print("Para fechar, volte aqui e pressione Ctrl+C.\n")
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        servidor.server_close()
    return 0
