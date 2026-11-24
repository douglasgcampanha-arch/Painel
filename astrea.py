#!/usr/bin/env python3
"""
Robô do Astrea (Aurum) - lança no Astrea as tarefas/prazos enviados pelo Painel.

O Astrea não tem API pública; o robô usa um navegador próprio (perfil em dados/perfil_astrea)
com o seu login, como faria você. Grava somente o que você confirmou no botão
"Enviar ao Astrea" do painel.

Uso:
  python astrea.py --login        # 1º acesso: janela visível para você entrar no Astrea
  python astrea.py --diagnostico  # grava a ESTRUTURA das telas (sem dados) para calibrar o robô
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DADOS = BASE / "dados"
PERFIL = DADOS / "perfil_astrea"
DIR_DIAG = DADOS / "astrea_diagnostico"
URL_PADRAO = "https://astrea.net.br"


def _url(cfg: dict) -> str:
    return (cfg.get("astrea", {}) or {}).get("url") or URL_PADRAO


def _contexto(p, headless: bool):
    PERFIL.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PERFIL), headless=headless, locale="pt-BR", timezone_id="America/Sao_Paulo",
        viewport={"width": 1366, "height": 900})


def _mascarar(t: str) -> str:
    t = re.sub(r"\S+@\S+", "<email>", t or "")
    t = re.sub(r"\d", "9", t)
    return re.sub(r"\s+", " ", t).strip()[:80]


JS_ESTRUTURA = r"""
() => {
  const vis = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
  const limpa = s => (s || '').replace(/\s+/g, ' ').trim();
  const rotulo = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return limpa(l.innerText); }
    const pai = el.closest('label'); if (pai) return limpa(pai.innerText);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) return limpa(lb.split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' '));
    return '';
  };
  const campos = [...document.querySelectorAll('input, textarea, select, [contenteditable="true"], [role="combobox"], [role="textbox"]')]
    .filter(vis).slice(0, 80).map(el => ({
      tag: el.tagName.toLowerCase(), tipo: el.type || el.getAttribute('role') || '',
      id: el.id || '', name: el.getAttribute('name') || '', placeholder: el.getAttribute('placeholder') || '',
      aria: el.getAttribute('aria-label') || '', rotulo: rotulo(el),
      classes: (el.className && el.className.baseVal === undefined ? el.className : '').toString().slice(0, 80),
      testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || ''
    }));
  const botoes = [...document.querySelectorAll('button, [role="button"], a.btn, input[type="submit"]')]
    .filter(vis).slice(0, 120).map(el => ({
      texto: limpa(el.innerText || el.value || '').slice(0, 60), aria: el.getAttribute('aria-label') || '',
      id: el.id || '', testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
      title: el.getAttribute('title') || ''
    }));
  const titulos = [...document.querySelectorAll('h1, h2, h3, h4, [role="dialog"] header, .modal-title')]
    .filter(vis).slice(0, 20).map(el => limpa(el.innerText).slice(0, 60));
  const dialogos = [...document.querySelectorAll('[role="dialog"], .modal, dialog')].filter(vis).length;
  const menus = [...document.querySelectorAll('nav a, aside a, [role="menuitem"], [role="tab"]')]
    .filter(vis).slice(0, 60).map(el => limpa(el.innerText).slice(0, 40)).filter(Boolean);
  return { campos, botoes, titulos, dialogos, menus };
}
"""


def login(cfg: dict) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _contexto(p, headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(_url(cfg), wait_until="domcontentloaded")
        input("\n>>> Entre no Astrea na janela que abriu (marque 'manter conectado', se houver).\n"
              ">>> Quando estiver na tela inicial do Astrea, volte aqui e tecle Enter.\n")
        print("Sessão salva no perfil do robô.")
        ctx.close()


def diagnostico(cfg: dict) -> Path:
    """Você navega; a cada Enter o robô grava a estrutura da tela (sem dados de clientes)."""
    from playwright.sync_api import sync_playwright
    DIR_DIAG.mkdir(parents=True, exist_ok=True)
    etapas = []
    roteiro = [
        "a tela de PROCESSOS (lista) com a busca visível",
        "um PROCESSO aberto (qualquer um)",
        "o formulário de NOVA TAREFA aberto (sem salvar), de preferência a partir do processo",
        "o formulário de NOVO PRAZO / ATIVIDADE aberto (sem salvar), se for diferente do de tarefa",
    ]
    with sync_playwright() as p:
        ctx = _contexto(p, headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(_url(cfg), wait_until="domcontentloaded")
        print("\nNavegue no Astrea pela janela do robô. NÃO salve nada; só abra as telas.")
        for passo in roteiro:
            r = input(f"\n>>> Abra {passo} e tecle Enter (ou digite 'p' para pular): ").strip().lower()
            if r == "p":
                continue
            pagina = ctx.pages[-1]
            try:
                estrutura = pagina.evaluate(JS_ESTRUTURA)
            except Exception as e:
                print(f"Não foi possível ler a tela: {e}")
                continue
            etapas.append({
                "etapa": passo,
                "caminho_url": _mascarar(re.sub(r"[?#].*$", "", pagina.url)),
                "titulo_pagina": _mascarar(pagina.title()),
                "titulos": [_mascarar(t) for t in estrutura["titulos"]],
                "dialogos_abertos": estrutura["dialogos"],
                "menus": [_mascarar(t) for t in estrutura["menus"]],
                "campos": [{k: (_mascarar(v) if isinstance(v, str) else v) for k, v in c.items()}
                           for c in estrutura["campos"]],
                "botoes": [{k: _mascarar(v) for k, v in b.items()} for b in estrutura["botoes"]],
            })
            print(f"   gravado: {len(estrutura['campos'])} campos, {len(estrutura['botoes'])} botões.")
        ctx.close()
    destino = DIR_DIAG / "estrutura.json"
    destino.write_text(json.dumps(etapas, ensure_ascii=False, indent=1), encoding="utf-8")
    return destino


def enviar(item: dict, cfg: dict, log) -> str:
    """Cria a tarefa/prazo no Astrea. Calibração pendente do diagnóstico das telas."""
    raise RuntimeError("Robô do Astrea ainda não calibrado: rode configurar_astrea.command "
                       "(diagnóstico das telas) e envie o arquivo estrutura.json para calibração.")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    from djen_painel import carregar_config
    cfg = carregar_config()
    if "--login" in sys.argv:
        login(cfg)
    elif "--diagnostico" in sys.argv:
        dest = diagnostico(cfg)
        print(f"\nEstrutura salva em {dest} (números mascarados, sem conteúdo de processos).")
    else:
        print(__doc__)
