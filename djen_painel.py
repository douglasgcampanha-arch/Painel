#!/usr/bin/env python3
"""
Painel DJEN - coletor de comunicações do Diário de Justiça Eletrônico Nacional.

Consulta a API pública do DJEN (comunicaapi.pje.jus.br) pelas OABs definidas em
config.json, acumula o histórico em dados/comunicacoes.json (sem duplicar) e gera
painel.html, um arquivo único e privado aberto direto no navegador.

A API bloqueia IPs fora do Brasil: rode este script em máquina com internet brasileira.
Somente biblioteca padrão do Python 3.9+ (nada a instalar).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import datajud

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
CONFIG_EXEMPLO = BASE / "config.exemplo.json"
DADOS = BASE / "dados"
ARQ_DADOS = DADOS / "comunicacoes.json"
ARQ_ESTADO = DADOS / "estado.json"
ARQ_CARTEIRA = DADOS / "processos.json"
ARQ_EPROC = DADOS / "eproc_tjsp.json"
ARQ_LOG = DADOS / "coletor.log"
TEMPLATE = BASE / "painel_template.html"
SAIDA = BASE / "painel.html"

API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
ITENS_POR_PAGINA = 100
USER_AGENT = "PainelDJEN/1.0 (uso pessoal)"


# ---------------------------------------------------------------- utilidades
def log(msg: str) -> None:
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linha)
    DADOS.mkdir(exist_ok=True)
    with ARQ_LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    # mantém o log enxuto (últimas 2000 linhas)
    linhas = ARQ_LOG.read_text(encoding="utf-8").splitlines()
    if len(linhas) > 2000:
        ARQ_LOG.write_text("\n".join(linhas[-2000:]) + "\n", encoding="utf-8")


def ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho: Path, conteudo) -> None:
    caminho.parent.mkdir(exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)


class _Stripper(HTMLParser):
    BLOCOS = {"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_data(self, data):
        self.partes.append(data)


def texto_limpo(bruto: str | None) -> str:
    if not bruto:
        return ""
    s = _Stripper()
    s.feed(bruto)
    txt = "".join(s.partes).replace("\xa0", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n\n", txt)
    return txt.strip()


# ------------------------------------------------- dias úteis (estimativa)
def _pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


_FERIADOS_CACHE: dict[int, set[date]] = {}


def feriados(ano: int) -> set[date]:
    """Feriados nacionais + pontos facultativos forenses usuais (Carnaval,
    Sexta-feira Santa, Corpus Christi). Não inclui feriados locais."""
    if ano not in _FERIADOS_CACHE:
        p = _pascoa(ano)
        fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
        moveis = [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)]
        _FERIADOS_CACHE[ano] = {date(ano, m, d) for m, d in fixos} | set(moveis)
    return _FERIADOS_CACHE[ano]


def dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in feriados(d.year)


def _suspenso(d: date) -> bool:
    """Recesso forense: prazos suspensos de 20/12 a 20/01 (CPC, art. 220; CLT, art. 775-A)."""
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


def prazo_fatal_estimado(inicio_iso: str, dias, tipo: str) -> str:
    """Último dia do prazo contado a partir do início estimado (inclusive).
    Dias úteis: pula fins de semana, feriados nacionais e o recesso de 20/12 a 20/01.
    Corridos: pula o recesso e, se terminar em dia não útil, prorroga para o próximo útil.
    Estimativa: não considera feriados locais, suspensões de expediente nem regras especiais."""
    if not inicio_iso or not isinstance(dias, int) or dias <= 0:
        return ""
    d = date.fromisoformat(inicio_iso)
    conta_dia = (lambda x: not _suspenso(x)) if tipo == "corridos" else (lambda x: dia_util(x) and not _suspenso(x))
    while not conta_dia(d):
        d += timedelta(days=1)
    restantes = dias - 1
    while restantes > 0:
        d += timedelta(days=1)
        if conta_dia(d):
            restantes -= 1
    while not dia_util(d):
        d += timedelta(days=1)
    return d.isoformat()


def proximo_dia_util(d: date) -> date:
    d += timedelta(days=1)
    while not dia_util(d):
        d += timedelta(days=1)
    return d


# --------------------------------------------------------------- API DJEN
def _get(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    espera = 5
    for tentativa in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")
            if e.code == 403 and "block access from your country" in corpo:
                raise RuntimeError(
                    "A API do DJEN recusou a conexão por bloqueio geográfico (IP fora do Brasil). "
                    "Rode o coletor em máquina com internet brasileira."
                ) from None
            if e.code in (429, 500, 502, 503, 504) and tentativa < 5:
                log(f"HTTP {e.code}; nova tentativa em {espera}s")
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError(f"HTTP {e.code} na API do DJEN: {corpo[:300]}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if tentativa < 5:
                log(f"Falha de rede ({e}); nova tentativa em {espera}s")
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError(f"Sem conexão com a API do DJEN: {e}") from None
    raise RuntimeError("Falha inesperada na consulta")


def consultar(oab: str, uf: str, inicio: date, fim: date) -> list[dict]:
    itens: list[dict] = []
    pagina = 1
    while True:
        resp = _get({
            "numeroOab": oab,
            "ufOab": uf,
            "dataDisponibilizacaoInicio": inicio.isoformat(),
            "dataDisponibilizacaoFim": fim.isoformat(),
            "itensPorPagina": ITENS_POR_PAGINA,
            "pagina": pagina,
        })
        lote = resp.get("items") or []
        itens.extend(lote)
        total = resp.get("count") or 0
        if not lote or len(lote) < ITENS_POR_PAGINA or len(itens) >= total:
            break
        pagina += 1
        time.sleep(1.5)  # respeita o limite de requisições
    return itens


def _primeiro(d: dict, *chaves, padrao=""):
    for k in chaves:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return padrao


def normalizar(item: dict, oab_ref: str) -> dict:
    disp = str(_primeiro(item, "data_disponibilizacao", "datadisponibilizacao", "dataDisponibilizacao"))[:10]
    try:
        d = date.fromisoformat(disp)
    except ValueError:
        try:
            d = datetime.strptime(disp, "%d/%m/%Y").date()
        except ValueError:
            d = None
    pub = proximo_dia_util(d) if d else None
    ini = proximo_dia_util(pub) if pub else None

    partes = []
    for dest in item.get("destinatarios") or []:
        nome = (dest.get("nome") or "").strip()
        if nome:
            polo = (dest.get("polo") or "").strip()
            partes.append(f"{nome} ({polo})" if polo else nome)

    advs = []
    for da in item.get("destinatarioadvogados") or []:
        a = da.get("advogado") or {}
        if a.get("nome"):
            advs.append(f"{a['nome']} – OAB {a.get('numero_oab', '')}/{a.get('uf_oab', '')}")

    return {
        "id": str(_primeiro(item, "id", "hash")),
        "disponibilizacao": d.isoformat() if d else disp,
        "publicacao_estimada": pub.isoformat() if pub else "",
        "inicio_prazo_estimado": ini.isoformat() if ini else "",
        "tribunal": _primeiro(item, "siglaTribunal", "sigla_tribunal"),
        "orgao": _primeiro(item, "nomeOrgao", "nome_orgao"),
        "classe": _primeiro(item, "nomeClasse", "nome_classe"),
        "tipo": _primeiro(item, "tipoComunicacao", "tipo_comunicacao"),
        "tipo_documento": _primeiro(item, "tipoDocumento", "tipo_documento"),
        "processo": _primeiro(item, "numeroprocessocommascara", "numero_processo", "numeroProcesso"),
        "meio": _primeiro(item, "meiocompleto", "meio"),
        "link": _primeiro(item, "link"),
        "partes": partes,
        "advogados": advs,
        "texto": texto_limpo(item.get("texto")),
        "oab_ref": oab_ref,
    }


# ------------------------------------------------------------------ painel
def gerar_painel(registros: dict, estado: dict, cfg: dict, carteira: dict | None = None,
                 eproc: dict | None = None) -> None:
    analises = ler_json(DADOS / "analises.json", {})
    def _com_analise(r):
        a = analises.get(r["id"])
        fatal = prazo_fatal_estimado(r.get("inicio_prazo_estimado", ""), (a or {}).get("prazo_dias"),
                                     (a or {}).get("prazo_tipo", "")) if a else ""
        return {**r, "analise": a, "prazo_fatal_estimado": fatal}
    lista = sorted((_com_analise(r) for r in registros.values()),
                   key=lambda r: (r["disponibilizacao"], r["id"]), reverse=True)
    processos = sorted((carteira or {}).values(),
                       key=lambda r: (r["movimentos"][0]["data"] if r.get("movimentos") else ""), reverse=True)
    payload = {
        "titular": cfg.get("titular", ""),
        "oabs": [f"{o['numero']}/{o['uf']}" for o in cfg["oabs"]],
        "atualizado_em": estado.get("ultima_execucao", ""),
        "ultimo_sucesso": estado.get("ultimo_sucesso", ""),
        "erro": estado.get("ultimo_erro", ""),
        "novas_ultima_coleta": estado.get("novas_ultima_coleta", 0),
        "comunicacoes": lista,
        "analise_ia_ativa": bool(cfg.get("analise_ia", {}).get("ativo")),
        "astrea_ativo": bool(cfg.get("astrea", {}).get("ativo")),
        "astrea_tipo_padrao": cfg.get("astrea", {}).get("tipo_padrao", "prazo"),
        "datajud": {
            "ativo": bool(cfg.get("datajud_ativo", True)),
            "ultima_execucao": estado.get("datajud_ultima_execucao", ""),
            "erro": estado.get("datajud_erro", ""),
            "resumo": estado.get("datajud_resumo", {}),
            "processos": processos,
        },
        "eproc": {"ativo": bool(cfg.get("eproc_tjsp", {}).get("ativo")), **(eproc or {})},
    }
    dados = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DADOS__*/null", dados)
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(SAIDA)


# -------------------------------------------------------------------- main
def carregar_config() -> dict:
    """Lê config.json (local, fora do Git). Se não existir, cria a partir do exemplo.
    Chaves novas do exemplo são acrescentadas sem alterar o que você já configurou."""
    exemplo = ler_json(CONFIG_EXEMPLO, {})
    if not CONFIG.exists() and exemplo:
        CONFIG.write_text(json.dumps(exemplo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cfg = ler_json(CONFIG, {})
    alterou = False
    for k, v in exemplo.items():
        if k not in cfg:
            cfg[k] = v
            alterou = True
        elif isinstance(v, dict) and isinstance(cfg[k], dict):
            for k2, v2 in v.items():
                if k2 not in cfg[k]:
                    cfg[k][k2] = v2
                    alterou = True
    if alterou:
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg



def main() -> int:
    cfg = carregar_config()
    if not cfg or not cfg.get("oabs"):
        print("config.json ausente ou sem OABs.", file=sys.stderr)
        return 2

    registros: dict = ler_json(ARQ_DADOS, {})
    estado: dict = ler_json(ARQ_ESTADO, {})
    hoje = date.today()
    estado["ultima_execucao"] = datetime.now().isoformat(timespec="seconds")

    # primeira execução: busca retroativa; depois, janela curta com sobreposição
    if estado.get("ultimo_sucesso"):
        inicio = hoje - timedelta(days=int(cfg.get("dias_sobreposicao", 3)))
    else:
        inicio = hoje - timedelta(days=int(cfg.get("janela_dias", 7)))

    novas = 0
    try:
        for o in cfg["oabs"]:
            ref = f"{o['numero']}/{o['uf']}"
            itens = consultar(str(o["numero"]), o["uf"].upper(), inicio, hoje)
            for it in itens:
                r = normalizar(it, ref)
                if not r["id"]:
                    continue
                if r["id"] not in registros:
                    r["capturado_em"] = estado["ultima_execucao"]
                    registros[r["id"]] = r
                    novas += 1
                else:
                    r["capturado_em"] = registros[r["id"]].get("capturado_em", estado["ultima_execucao"])
                    registros[r["id"]] = r
            log(f"OAB {ref}: {len(itens)} comunicações entre {inicio} e {hoje}")
        estado["ultimo_sucesso"] = estado["ultima_execucao"]
        estado["ultimo_erro"] = ""
        estado["novas_ultima_coleta"] = novas
        # mantém somente a janela configurada (padrão: últimos 7 dias)
        corte = (hoje - timedelta(days=int(cfg.get("janela_dias", 7)))).isoformat()
        for k in [k for k, r in registros.items() if (r.get("disponibilizacao") or "") < corte]:
            del registros[k]
        gravar_json(ARQ_DADOS, registros)
        log(f"Coleta concluída: {novas} nova(s); {len(registros)} no histórico")
        codigo = 0
    except Exception as e:  # registra e ainda gera o painel com o histórico
        estado["ultimo_erro"] = str(e)
        log(f"ERRO: {e}")
        codigo = 1

    # ---- eproc TJSP (login com certificado; somente leitura)
    eproc = ler_json(ARQ_EPROC, {})
    ecfg = cfg.get("eproc_tjsp", {})
    if ecfg.get("ativo"):
        agora = datetime.now()
        ult = eproc.get("ultima_execucao")
        vencido = not ult or agora - datetime.fromisoformat(ult) >= timedelta(hours=float(ecfg.get("intervalo_horas", 2)))
        no_horario = int(ecfg.get("horario_inicio", 7)) <= agora.hour < int(ecfg.get("horario_fim", 21))
        if vencido and no_horario and not eproc.get("precisa_2fa"):
            try:
                import eproc_tjsp
                eproc = eproc_tjsp.coletar(cfg, log)
            except ImportError as e:
                eproc["erro"] = f"Playwright não instalado ({e}). Rode instalar_mac.command."
                log(f"ERRO eproc TJSP: {eproc['erro']}")

    # painel parcial já atualizado antes do DataJud (que pode demorar)
    carteira: dict = ler_json(ARQ_CARTEIRA, {})
    gravar_json(ARQ_ESTADO, estado)
    gerar_painel(registros, estado, cfg, carteira, eproc)

    # ---- Análise das publicações com IA (cliente, manifestação, orientação)
    if cfg.get("analise_ia", {}).get("ativo"):
        try:
            import analise_ia
            analise_ia.analisar_pendentes(registros, cfg, log)
            gerar_painel(registros, estado, cfg, carteira, eproc)
        except Exception as e:
            log(f"ERRO Análise IA: {e}")

    # ---- DataJud: movimentações da carteira (todos os sistemas: PJe, eproc, e-SAJ, Projudi...)
    # se a última rodada foi interrompida por instabilidade do CNJ, espera algumas horas
    pausa_dj = False
    if estado.get("datajud_resumo", {}).get("interrompido") and estado.get("datajud_ultima_execucao"):
        decorrido = datetime.now() - datetime.fromisoformat(estado["datajud_ultima_execucao"])
        pausa_dj = decorrido < timedelta(hours=float(cfg.get("datajud_pausa_horas", 3)))
        if pausa_dj:
            log("DataJud em pausa após instabilidade; nova tentativa mais tarde.")
    if cfg.get("datajud_ativo", True) and not pausa_dj:
        numeros = {}
        for r in registros.values():
            n = datajud.so_digitos(r.get("processo", ""))
            if len(n) == 20:
                numeros[n] = r.get("tribunal", "")
        try:
            resumo = datajud.atualizar_carteira(carteira, numeros, cfg, log)
            estado["datajud_resumo"] = resumo
            estado["datajud_erro"] = ""
            log(f"DataJud: {resumo['consultados']} processo(s) consultado(s), "
                f"{resumo['novas_movimentacoes']} movimentação(ões) nova(s), {resumo['erros']} erro(s)")
        except Exception as e:
            estado["datajud_erro"] = str(e)
            log(f"ERRO DataJud: {e}")
        estado["datajud_ultima_execucao"] = datetime.now().isoformat(timespec="seconds")
        gravar_json(ARQ_CARTEIRA, carteira)

    gravar_json(ARQ_ESTADO, estado)
    gerar_painel(registros, estado, cfg, carteira, eproc)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
