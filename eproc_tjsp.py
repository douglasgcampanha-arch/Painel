#!/usr/bin/env python3
"""
Conector eproc TJSP - leitura das citações/intimações do Painel do Advogado.

Login com certificado digital A1 (.pfx) apresentado na conexão TLS ao SSO do TJSP
(certificado-sso.tjsp.jus.br). O 2FA é resolvido de uma destas formas:
  1) dispositivo liberado ("Não usar o 2FA neste dispositivo e navegador"), marcado
     uma única vez no modo --interativo; o perfil do navegador fica salvo em dados/;
  2) opcionalmente, código TOTP gerado a partir da chave do autenticador guardada
     nas Chaves do macOS (serviço "painel-eproc-totp").

SOMENTE LEITURA. O robô nunca aciona "Abrir Prazo" nem abre o teor de atos:
há trava por texto do elemento e bloqueio de requisições suspeitas.

Uso:
  python eproc_tjsp.py --interativo   # 1º acesso: janela visível para validar o 2FA
  python eproc_tjsp.py                # coleta (headless) - chamado pelo djen_painel.py
  python eproc_tjsp.py --diagnostico  # salva estrutura das telas, sem dados de processos
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DADOS = BASE / "dados"
PERFIL = DADOS / "perfil_eproc"
ARQ_SAIDA = DADOS / "eproc_tjsp.json"
DIR_DIAG = DADOS / "eproc_diagnostico"

URL_INICIAL = "https://eproc1g.tjsp.jus.br/eproc/"
ORIGEM_CERT = "https://certificado-sso.tjsp.jus.br"
KC_SERVICO_SENHA = "painel-eproc-certificado"
KC_SERVICO_TOTP = "painel-eproc-totp"

# ---- travas de segurança (nada que gere ciência/abertura de prazo) ----------
TEXTO_PROIBIDO = re.compile(
    r"abrir\s*prazo|abertura\s*de\s*prazo|confirmar|ci[eê]ncia|renunciar|"
    r"responder|peticionar|assinar|excluir|cancelar\s*dispositivos|desativar",
    re.I,
)
URL_PROIBIDA = re.compile(
    r"abrir_?prazo|prazo_?abrir|confirmar|ciencia|renuncia|intimacao_?abrir|"
    r"peticionamento|assinatura|desativar|cancelar_dispositivo|logout|sair",
    re.I,
)
CNJ = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")


class Precisa2FA(RuntimeError):
    pass


# ------------------------------------------------------------- utilidades
def _keychain(servico: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", servico, "-w"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        return None


def _totp(segredo_b32: str, passo: int = 30, digitos: int = 6) -> str:
    chave = base64.b32decode(segredo_b32.replace(" ", "").upper() + "=" * (-len(segredo_b32.replace(" ", "")) % 8))
    contador = struct.pack(">Q", int(time.time()) // passo)
    h = hmac.new(chave, contador, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    codigo = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digitos)
    return str(codigo).zfill(digitos)


def _notificar(titulo: str, texto: str) -> None:
    if sys.platform == "darwin":
        t = texto.replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{t}" with title "{titulo}"'],
                       capture_output=True, timeout=10)


def _mascarar(txt: str) -> str:
    """Para o diagnóstico: remove números e nomes (mantém só a estrutura)."""
    txt = re.sub(r"\d", "9", txt or "")
    return txt[:80]


# --------------------------------------------------------- JS de leitura
JS_TABELAS = r"""
() => {
  const limpa = s => (s || '').replace(/\s+/g, ' ').trim();
  return [...document.querySelectorAll('table')].map((t, i) => {
    let heads = [...t.querySelectorAll('thead th')].map(th => limpa(th.innerText));
    let rows = [...t.querySelectorAll('tbody tr')];
    if (!heads.length && rows.length) {
      const first = rows[0];
      const ths = first.querySelectorAll('th');
      if (ths.length) { heads = [...ths].map(th => limpa(th.innerText)); rows = rows.slice(1); }
    }
    return {
      idx: i, id: t.id || '', classe: t.className || '', caption: limpa(t.caption && t.caption.innerText),
      heads,
      rows: rows.map(tr => [...tr.querySelectorAll('td')].map(td => limpa(td.innerText))).filter(r => r.length),
    };
  });
}
"""

JS_SECAO_INTIMACOES = r"""
() => {
  const limpa = s => (s || '').replace(/\s+/g, ' ').trim();
  // menor bloco que contém o título "Citações/Intimações"
  const cands = [...document.querySelectorAll('fieldset, section, div, table')]
    .filter(el => /cita[cç][oõ]es\s*\/\s*intima[cç][oõ]es/i.test(el.innerText || ''))
    .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
  const bloco = cands.find(el => el.querySelectorAll('a').length > 0);
  if (!bloco) return null;
  bloco.setAttribute('data-painel-secao', 'intimacoes');
  const abas = [...bloco.querySelectorAll('a, button, li')]
    .map(el => limpa(el.innerText))
    .filter(t => /^(SP|TJSP|EF)$/.test(t));
  const itens = [];
  bloco.querySelectorAll('a').forEach((a, i) => {
    const t = limpa(a.innerText);
    if (!/^\d+$/.test(t)) return;
    if (!a.getClientRects().length || getComputedStyle(a).visibility === 'hidden') return; // ignora abas ocultas
    // rótulo = texto da linha/caixa onde está o número
    const linha = a.closest('tr, li, .card, .row, div') || a.parentElement;
    const rotulo = limpa((linha.innerText || '').replace(t, ''));
    a.setAttribute('data-painel-idx', String(i));
    itens.push({ idx: String(i), quantidade: parseInt(t, 10), categoria: rotulo.slice(0, 160),
                 href: a.getAttribute('href') || '', onclick: a.getAttribute('onclick') || '' });
  });
  return { abas: [...new Set(abas)], itens };
}
"""


# --------------------------------------------------------------- coletor
class ColetorEproc:
    def __init__(self, cfg: dict, log, interativo=False, diagnostico=False):
        self.cfg = cfg
        self.log = log
        self.interativo = interativo
        self.diagnostico = diagnostico
        self.diag: list[dict] = []

    # -- segurança
    def _guarda_rotas(self, rota):
        url = rota.request.url
        if URL_PROIBIDA.search(url.split("?", 1)[-1] if "?" in url else "") and "sso" not in url:
            self.log(f"eproc: requisição bloqueada por segurança: {url[:120]}")
            return rota.abort()
        return rota.continue_()

    def _clique_seguro(self, el, pagina):
        texto = (el.inner_text() or "") + " " + (el.get_attribute("title") or "")
        href = (el.get_attribute("href") or "") + " " + (el.get_attribute("onclick") or "")
        if TEXTO_PROIBIDO.search(texto) or URL_PROIBIDA.search(href):
            raise RuntimeError(f"Trava de segurança: clique recusado em '{texto.strip()[:60]}'")
        el.click()
        pagina.wait_for_load_state("domcontentloaded")

    def _registrar_diag(self, pagina, etapa: str):
        if not self.diagnostico:
            return
        DIR_DIAG.mkdir(parents=True, exist_ok=True)
        tabelas = pagina.evaluate(JS_TABELAS)
        acoes = sorted(set(re.findall(r"acao=([A-Za-z0-9_/]+)", pagina.content())))
        self.diag.append({
            "etapa": etapa,
            "url_acao": re.findall(r"acao=([A-Za-z0-9_/]+)", pagina.url),
            "titulo": pagina.title(),
            "acoes_na_pagina": acoes,
            "tabelas": [{"id": t["id"], "classe": t["classe"], "colunas": t["heads"], "linhas": len(t["rows"]),
                         "exemplo_mascarado": [_mascarar(c) for c in (t["rows"][0] if t["rows"] else [])]}
                        for t in tabelas],
            "inputs": pagina.evaluate("""() => [...document.querySelectorAll('input,button,select')]
                .map(e => ({tag:e.tagName, id:e.id, name:e.name, type:e.type,
                            label:(['submit','button'].includes(e.type)||e.tagName==='BUTTON')
                                   ? (e.value||e.innerText||'').slice(0,40) : ''}))"""),
        })

    # -- login
    def _logado(self, pagina) -> bool:
        return "eproc1g.tjsp.jus.br" in pagina.url and "sso" not in pagina.url and \
            pagina.locator("text=/Painel do Advogado|Cita[cç][oõ]es\\/Intima[cç][oõ]es/i").count() > 0

    def _login(self, pagina):
        pagina.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90000)
        if self._logado(pagina):
            return
        self._registrar_diag(pagina, "tela_login")
        botao = pagina.locator("#kc-login-certificate")
        if botao.count() == 0:
            raise RuntimeError("Botão de login por certificado não encontrado (tela de login mudou).")
        botao.click()
        pagina.wait_for_load_state("domcontentloaded", timeout=90000)
        self._registrar_diag(pagina, "apos_certificado")

        # Keycloak X.509: tela de confirmação do certificado ("Continuar")
        for _ in range(3):
            if self._logado(pagina):
                return
            cont = pagina.locator("#kc-login, input[name=login], button[name=login]")
            otp = pagina.locator("input[name=otp], input#otp, input[autocomplete=one-time-code], "
                                 "input[name=totp], input[maxlength='6']")
            if otp.count():
                self._resolver_2fa(pagina, otp.first)
            elif cont.count():
                cont.first.click()
                pagina.wait_for_load_state("domcontentloaded", timeout=90000)
            else:
                pagina.wait_for_timeout(2000)
        if not self._logado(pagina):
            erro = pagina.locator(".alert, .kc-feedback-text, #input-error").all_inner_texts()
            raise RuntimeError("Login no eproc não concluído. " + " ".join(erro)[:200])

    def _resolver_2fa(self, pagina, campo):
        self._registrar_diag(pagina, "tela_2fa")
        lembrar = pagina.locator("label:has-text('Não usar o 2FA') input, input[type=checkbox]")
        segredo = _keychain(KC_SERVICO_TOTP)
        if segredo:
            campo.fill(_totp(segredo))
            if lembrar.count():
                lembrar.first.check()
            pagina.locator("#kc-login, input[type=submit], button[type=submit]").first.click()
            pagina.wait_for_load_state("domcontentloaded", timeout=90000)
            return
        if self.interativo:
            if lembrar.count():
                try:
                    lembrar.first.check()
                except Exception:
                    pass
            print("\n>>> Digite o código do autenticador na janela do navegador, mantenha marcada a opção\n"
                  ">>> 'Não usar o 2FA neste dispositivo e navegador' e clique em Validar.\n"
                  ">>> Aguardando até 5 minutos...\n")
            pagina.wait_for_url(re.compile(r"eproc1g\.tjsp\.jus\.br/eproc/(?!.*sso)"), timeout=300000)
            pagina.wait_for_load_state("domcontentloaded")
            return
        raise Precisa2FA("O eproc pediu o código 2FA. Rode 'eproc_primeiro_acesso.command' (modo interativo) "
                         "para liberar este dispositivo novamente.")

    # -- leitura
    def _ler_secao(self, pagina) -> list[dict]:
        resultado = []
        secao = pagina.evaluate(JS_SECAO_INTIMACOES)
        if not secao:
            raise RuntimeError("Seção 'Citações/Intimações' não encontrada no Painel do Advogado.")
        abas = secao["abas"] or [""]
        for aba in abas:
            if aba:
                el = pagina.locator("[data-painel-secao=intimacoes]").get_by_text(aba, exact=True).first
                self._clique_seguro(el, pagina)
                pagina.wait_for_timeout(1500)
                secao = pagina.evaluate(JS_SECAO_INTIMACOES) or {"itens": []}
            self._registrar_diag(pagina, f"painel_aba_{aba or 'unica'}")
            if self.diagnostico and self.diag:
                self.diag[-1]["categorias"] = [{"categoria": i["categoria"], "tem_link": bool(i["href"] or i["onclick"])}
                                               for i in secao["itens"]]
            for it in secao["itens"]:
                resultado.append({"base": aba or "SP", **it})
        # remove repetições (mesma base + categoria)
        unicos = {}
        for r in resultado:
            unicos.setdefault((r["base"], r["categoria"]), r)
        return list(unicos.values())

    def _ler_lista(self, contexto, pagina_painel, item) -> list[dict]:
        """Abre a lista de processos de uma categoria (link do número) numa aba nova e lê a tabela."""
        el = pagina_painel.locator(f"[data-painel-idx='{item['idx']}']")
        texto = (el.inner_text() or "")
        if TEXTO_PROIBIDO.search(texto) or URL_PROIBIDA.search(item["href"] + item["onclick"]):
            raise RuntimeError("Trava de segurança: link de categoria suspeito.")
        if item["href"] and not item["href"].startswith(("javascript", "#")):
            pg = contexto.new_page()
            pg.goto(el.evaluate("a => a.href"), wait_until="domcontentloaded", timeout=90000)
        else:
            with contexto.expect_page(timeout=15000) as nova:
                el.click(modifiers=["Meta"] if sys.platform == "darwin" else ["Control"])
            pg = nova.value
            pg.wait_for_load_state("domcontentloaded")
        self._registrar_diag(pg, f"lista_{item['base']}_{_mascarar(item['categoria'])[:30]}")
        linhas = []
        for t in pg.evaluate(JS_TABELAS):
            heads = t["heads"]
            if not any(re.search(r"processo", h, re.I) for h in heads):
                continue
            for r in t["rows"]:
                proc = next((m.group(0) for c in r for m in [CNJ.search(c)] if m), "")
                if not proc:
                    continue
                cols = {(heads[i] if i < len(heads) and heads[i] else f"col{i+1}"): v for i, v in enumerate(r) if v}
                linhas.append({"processo": proc, "colunas": cols})
        pg.close()
        return linhas

    def executar(self) -> dict:
        from playwright.sync_api import sync_playwright

        e = self.cfg.get("eproc_tjsp", {})
        def _caminho(c):
            c = Path(c).expanduser()
            return c if c.is_absolute() else BASE / c
        pfx = str(_caminho(e["certificado_pfx"])) if e.get("certificado_pfx") else ""
        senha = _keychain(KC_SERVICO_SENHA)
        if not pfx or not Path(pfx).exists():
            raise RuntimeError("Arquivo do certificado (.pfx) não encontrado. Ajuste 'eproc_tjsp.certificado_pfx' no config.json.")
        if not senha:
            raise RuntimeError("Senha do certificado não encontrada nas Chaves do macOS (serviço painel-eproc-certificado).")
        cert = {"origin": ORIGEM_CERT, "pfxPath": pfx, "passphrase": senha}
        if e.get("certificado_pem") and e.get("chave_pem"):  # alternativa p/ .pfx com criptografia legada
            cert = {"origin": ORIGEM_CERT, "certPath": str(_caminho(e["certificado_pem"])),
                    "keyPath": str(_caminho(e["chave_pem"])), "passphrase": senha}

        PERFIL.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(PERFIL), headless=not self.interativo, client_certificates=[cert],
                locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1366, "height": 900},
            )
            ctx.route("**/*", self._guarda_rotas)
            try:
                pagina = ctx.pages[0] if ctx.pages else ctx.new_page()
                self._login(pagina)
                self._registrar_diag(pagina, "painel_advogado")
                categorias = self._ler_secao(pagina)
                itens, vistos = [], set()
                for c in categorias:
                    if c["quantidade"] <= 0:
                        continue
                    for linha in self._ler_lista(ctx, pagina, c):
                        chave = (c["base"], c["categoria"], linha["processo"])
                        if chave not in vistos:
                            vistos.add(chave)
                            itens.append({"base": c["base"], "categoria": c["categoria"], **linha})
                    time.sleep(1.5)
            finally:
                if self.diagnostico:
                    (DIR_DIAG / "estrutura.json").write_text(json.dumps(self.diag, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
                ctx.close()
        return {"categorias": [{k: c[k] for k in ("base", "categoria", "quantidade")} for c in categorias],
                "itens": itens}


# ------------------------------------------------------- integração painel
def coletar(cfg: dict, log, interativo=False, diagnostico=False) -> dict:
    """Executa a coleta e grava dados/eproc_tjsp.json mantendo 'visto_em' dos itens."""
    anterior = {}
    try:
        anterior = json.loads(ARQ_SAIDA.read_text(encoding="utf-8"))
    except Exception:
        pass
    agora = datetime.now().isoformat(timespec="seconds")
    saida = {**anterior, "ultima_execucao": agora}
    vistos_antes = {f"{i['base']}|{i['categoria']}|{i['processo']}": i.get("visto_em", agora)
                    for i in anterior.get("itens", [])}
    try:
        r = ColetorEproc(cfg, log, interativo, diagnostico).executar()
        for i in r["itens"]:
            i["visto_em"] = vistos_antes.get(f"{i['base']}|{i['categoria']}|{i['processo']}", agora)
        saida.update(r, ultimo_sucesso=agora, erro="", precisa_2fa=False)
        log(f"eproc TJSP: {len(r['itens'])} processo(s) em {len(r['categorias'])} categoria(s)")
    except ModuleNotFoundError as ex:
        saida.update(erro=f"Playwright não instalado ({ex}). Rode instalar_mac.command.", precisa_2fa=False)
        log(f"ERRO eproc TJSP: {saida['erro']}")
    except Precisa2FA as ex:
        saida.update(erro=str(ex), precisa_2fa=True)
        log(f"eproc TJSP: {ex}")
        _notificar("Painel - eproc TJSP", "É preciso validar o 2FA novamente.")
    except Exception as ex:
        saida.update(erro=str(ex), precisa_2fa=False)
        log(f"ERRO eproc TJSP: {ex}")
    DADOS.mkdir(exist_ok=True)
    ARQ_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    return saida


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    from djen_painel import carregar_config, log as _log
    cfg = carregar_config()
    res = coletar(cfg, _log, interativo="--interativo" in sys.argv, diagnostico="--diagnostico" in sys.argv)
    if "--diagnostico" in sys.argv:
        print(f"Estrutura salva em {DIR_DIAG / 'estrutura.json'} (sem números de processos ou nomes).")
    sys.exit(0 if not res.get("erro") else 1)
