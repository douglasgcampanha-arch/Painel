#!/usr/bin/env python3
"""
Robô do Astrea (Aurum) - lança no Astrea as tarefas/prazos enviados pelo Painel.

O Astrea não tem API pública; o robô usa um navegador próprio (perfil em dados/perfil_astrea)
com o seu login, como faria você. Grava somente o que você confirmou no botão
"Enviar ao Astrea" do painel.

Uso:
  python astrea.py --login        # 1º acesso: janela visível para você entrar no Astrea
  python astrea.py --diagnostico  # grava a ESTRUTURA das telas (sem dados) para calibrar o robô
  python astrea.py --gravar       # grava os cliques ao criar UM prazo de teste (calibração fina)
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


DIR_ERROS = DADOS / "astrea_erros"
CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


def _mascara_cnj(n: str) -> str:
    d = re.sub(r"\D", "", n or "")
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}" if len(d) == 20 else (n or "")


def _data_br(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _visivel(loc) -> bool:
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _abrir_processo(pg, numero: str, cfg: dict) -> None:
    """Pesquisa o processo pelo número na busca global e abre o resultado correspondente."""
    alvo = _mascara_cnj(numero)
    digitos = re.sub(r"\D", "", numero)
    pg.goto(_url(cfg), wait_until="domcontentloaded", timeout=90000)
    busca = pg.locator("input#search")
    for _ in range(60):
        if _visivel(busca):
            break
        if _visivel(pg.locator('input[type="password"]')):
            raise RuntimeError("Sessão do Astrea expirada: rode 'astrea.py --login' (ou configurar_astrea.command).")
        pg.wait_for_timeout(1000)
    else:
        raise RuntimeError("Tela inicial do Astrea não carregou (campo de pesquisa não apareceu).")
    for termo in (alvo, digitos):
        busca.first.click()
        busca.first.fill("")
        busca.first.type(termo, delay=30)
        pg.wait_for_timeout(2500)
        if not _visivel(pg.get_by_text(alvo, exact=False).filter(has_not=pg.locator("input"))):
            busca.first.press("Enter")
            pg.wait_for_timeout(2500)
        # resultado que contenha o número (com ou sem máscara), fora do próprio campo de busca
        for cand in (alvo, digitos):
            res = pg.get_by_text(cand, exact=False).filter(has_not=pg.locator("input"))
            for k in range(min(res.count(), 6)):
                el = res.nth(k)
                if el.is_visible():
                    el.click()
                    pg.wait_for_timeout(3000)
                    if _visivel(pg.get_by_text("Atividades", exact=True)) or _visivel(pg.get_by_text("Resumo", exact=True)):
                        return
    raise RuntimeError(f"Processo {alvo} não localizado no Astrea pela busca.")


def _opcao_prazo(pg):
    """Item de menu 'Prazo' (ignora títulos de seção como 'PRAZO')."""
    rx = re.compile(r"^\s*(adicionar\s+|novo\s+)?prazo\s*$", re.I)
    for sel in ('[role="menuitem"]', '[role="option"]', "li", "button", "a", "span, div"):
        cands = pg.locator(sel).filter(has_text=rx)
        for k in range(min(cands.count(), 10)):
            el = cands.nth(k)
            try:
                if not el.is_visible() or not rx.match(el.inner_text() or ""):
                    continue
                if el.evaluate("e => /^H[1-6]$/.test(e.tagName) || !!e.closest('h1,h2,h3,h4,h5,h6')"):
                    continue
                return el
            except Exception:
                continue
    return None


def _abrir_form_prazo(pg) -> None:
    """Abre o formulário 'Adicionar prazo' a partir da tela do processo."""
    titulo_form = pg.get_by_text("Adicionar prazo", exact=True)
    if _visivel(titulo_form):
        return
    # 1) aba Atividades, se existir
    aba = pg.get_by_text("Atividades", exact=True)
    if _visivel(aba):
        aba.first.click()
        pg.wait_for_timeout(1500)
    # 2) botões "Adicionar" da área do processo (ignora o primeiro, da barra superior)
    botoes = pg.locator('[aria-label="Adicionar"]')
    for k in range(1, min(botoes.count(), 12)):
        b = botoes.nth(k)
        if not b.is_visible():
            continue
        b.click()
        pg.wait_for_timeout(1000)
        if _visivel(titulo_form):
            return
        opcao = _opcao_prazo(pg)
        if opcao is not None:
            opcao.click()
            pg.wait_for_timeout(1500)
            if _visivel(titulo_form) or _visivel(pg.locator("input#name")):
                return
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)
    raise RuntimeError("Não encontrei o botão que abre 'Adicionar prazo' no processo (gravar_cliques ajuda a calibrar).")


def _preencher_prazo(pg, item: dict, cfg: dict) -> None:
    acfg = cfg.get("astrea", {})
    nome = pg.locator("input#name")
    nome.first.wait_for(state="visible", timeout=20000)
    nome.first.fill(item["titulo"][:200])

    data = _data_br(item.get("data", ""))
    if not data:
        raise RuntimeError("Prazo sem data: informe a data na janela de envio.")
    campo_data = pg.locator("input#dueDate")
    campo_data.first.click()
    campo_data.first.fill("")
    campo_data.first.type(data, delay=40)
    pg.keyboard.press("Escape")  # fecha o calendário

    dias = int(acfg.get("lembrete_dias_antes", 2))
    alerta = pg.locator("input#alertNumTimeUnit")
    if _visivel(alerta):
        alerta.first.fill(str(dias))
        unidade = pg.locator("select#alertTimeUnit")
        if _visivel(unidade):
            opcoes = unidade.first.locator("option").all_inner_texts()
            dia = next((o for o in opcoes if re.search(r"dia", o, re.I)), None)
            if dia:
                unidade.first.select_option(label=dia)

    resp = (acfg.get("responsavel") or "").strip()
    if resp:
        campo = pg.locator('[data-testid="suggestComponent-input"]')
        if _visivel(campo):
            campo.first.fill(resp)
            pg.wait_for_timeout(1200)
            sug = pg.get_by_text(resp, exact=False)
            if _visivel(sug):
                sug.first.click()

    obs = pg.locator("textarea#comments")
    if _visivel(obs):
        obs.first.fill(item.get("descricao", "")[:15000])


def _botao_salvar(pg):
    cand = pg.get_by_role("button", name=re.compile(r"^\s*(salvar|adicionar prazo|criar|confirmar)\s*$", re.I))
    for k in range(cand.count()):
        if cand.nth(k).is_visible():
            return cand.nth(k)
    return None


def enviar(item: dict, cfg: dict, log) -> str:
    """Cria o prazo no Astrea vinculado ao processo (pelo número CNJ).
    Padrões (config.json > astrea): responsável = usuário logado (campo 'responsavel' vazio),
    lembrete 'lembrete_dias_antes' dias antes do vencimento (padrão 2).
    'salvar_automatico' (padrão false): com false, a janela fica aberta para você conferir e
    clicar em Salvar no Astrea; o robô aguarda e confirma."""
    from playwright.sync_api import sync_playwright

    acfg = cfg.get("astrea", {})
    automatico = bool(acfg.get("salvar_automatico", False))
    with sync_playwright() as p:
        ctx = _contexto(p, headless=automatico)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _abrir_processo(pg, item["processo"], cfg)
            _abrir_form_prazo(pg)
            _preencher_prazo(pg, item, cfg)
            titulo = item["titulo"][:200]
            if automatico:
                b = _botao_salvar(pg)
                if not b:
                    raise RuntimeError("Botão de salvar não encontrado (mude salvar_automatico para false).")
                b.click()
            else:
                log(f"Astrea: formulário preenchido para {item['processo']}; aguardando você clicar em Salvar.")
                # espera o formulário fechar (até 15 min)
                pg.locator("input#name").first.wait_for(state="detached", timeout=15 * 60 * 1000)
            pg.wait_for_timeout(2500)
            if _visivel(pg.get_by_text(titulo[:60], exact=False)):
                return "prazo criado"
            raise RuntimeError("O formulário fechou, mas o prazo não apareceu no processo (cancelado?).")
        except Exception:
            DIR_ERROS.mkdir(parents=True, exist_ok=True)
            try:
                pg.screenshot(path=str(DIR_ERROS / f"erro_{datetime.now():%Y%m%d_%H%M%S}.png"))
            except Exception:
                pass
            raise
        finally:
            ctx.close()


JS_GRAVADOR = r"""
() => {
  if (window.__gravador) return; window.__gravador = [];
  const limpa = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, 50);
  document.addEventListener('click', ev => {
    const el = ev.target.closest('button, a, [role], input, select, textarea, li, span, div');
    if (!el) return;
    const caixa = el.closest('[role="dialog"], form, section, aside') || document.body;
    const tit = caixa.querySelector('h1,h2,h3,h4');
    window.__gravador.push({
      tag: el.tagName.toLowerCase(), texto: limpa(el.innerText || el.value), aria: el.getAttribute('aria-label') || '',
      testid: el.getAttribute('data-testid') || '', id: el.id || '', role: el.getAttribute('role') || '',
      classes: String(el.className || '').slice(0, 60), contexto: limpa(tit && tit.innerText)
    });
  }, true);
}
"""


def gravar_cliques(cfg: dict) -> Path:
    """Grava os cliques enquanto você cria UM prazo de teste no Astrea (apague-o depois)."""
    from playwright.sync_api import sync_playwright
    DIR_DIAG.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _contexto(p, headless=False)
        ctx.add_init_script(f"({JS_GRAVADOR})()")
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(_url(cfg), wait_until="domcontentloaded")
        pg.evaluate(JS_GRAVADOR)
        input("\n>>> Na janela do robô: pesquise um processo, abra-o, clique para adicionar um PRAZO,\n"
              ">>> preencha com dados de teste e clique em SALVAR. Depois volte aqui e tecle Enter.\n")
        cliques = []
        for pagina in ctx.pages:
            try:
                cliques += pagina.evaluate("() => window.__gravador || []")
            except Exception:
                pass
        ctx.close()
    for c in cliques:
        for k in ("texto", "contexto"):
            c[k] = _mascarar(c[k])
    destino = DIR_DIAG / "cliques.json"
    destino.write_text(json.dumps(cliques, ensure_ascii=False, indent=1), encoding="utf-8")
    return destino


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    from djen_painel import carregar_config
    cfg = carregar_config()
    if "--login" in sys.argv:
        login(cfg)
    elif "--gravar" in sys.argv:
        dest = gravar_cliques(cfg)
        print(f"\nCliques salvos em {dest}. Lembre de apagar o prazo de teste no Astrea.")
    elif "--diagnostico" in sys.argv:
        dest = diagnostico(cfg)
        print(f"\nEstrutura salva em {dest} (números mascarados, sem conteúdo de processos).")
    else:
        print(__doc__)
