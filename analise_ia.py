"""
Análise das publicações do DJEN com o Claude (API da Anthropic).

Para cada comunicação nova da janela de dias, gera uma análise estruturada:
- se o ato é dirigido ao cliente do escritório (e qual parte/polo);
- se exige manifestação, qual providência e o prazo;
- orientação prática, checklist e estrutura da peça para deixar preparado.

A análise é gerada pelo coletor (não pelo navegador) e gravada em dados/analises.json;
o botão "Análise" do painel apenas exibe o resultado.

Motores (config.json > analise_ia > motor):
- "claude_cli" (padrão): usa o Claude Code instalado no Mac, logado com a assinatura do
  Claude. Sem chave de API e sem cobrança extra; consome o limite de uso da assinatura.
- "api": usa a API da Anthropic com chave (Chaves do macOS "painel-anthropic-api").
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ARQ_ANALISES = BASE / "dados" / "analises.json"
KC_SERVICO_API = "painel-anthropic-api"
KC_SERVICO_OAUTH = "painel-claude-oauth"   # opcional: token de `claude setup-token`
DIR_TRABALHO = BASE / "dados" / "ia_tmp"   # pasta vazia: o Claude Code não lê arquivos do projeto
VERSAO_PROMPT = 1

SISTEMA = """Você é um advogado sênior brasileiro que faz a triagem diária das publicações do \
Diário de Justiça Eletrônico Nacional (DJEN) para um escritório de advocacia. Seu trabalho é ler \
a publicação e dizer ao advogado responsável, de forma objetiva e técnica, se ela diz respeito ao \
cliente dele, se exige manifestação, em que prazo e como deixar a providência preparada.

Regras:
- Baseie-se somente no texto da publicação e nos dados fornecidos. Não invente fatos, números de \
processo, decisões anteriores, jurisprudência ou súmulas. Cite dispositivo legal apenas quando tiver \
certeza de que se aplica (ex.: CPC, CLT, Lei 9.099/95, Lei 11.419/2006, CTB); na dúvida, não cite.
- Se o texto for insuficiente, truncado ou ambíguo, diga isso e marque o campo como "verificar".
- Cliente: o advogado é quem está identificado como usuário (nome/OAB). O cliente é a parte que ele \
representa. Use a lista de clientes conhecidos, os polos e o próprio texto (ex.: "intime-se a parte \
autora", "manifeste-se o réu") para concluir. Se não for possível afirmar, responda "incerto" e \
explique o que falta.
- O ato "é dirigido ao cliente" quando determina algo à parte representada pelo advogado ou lhe \
dá ciência de algo que afeta seu interesse (decisão, sentença, prazo comum às partes etc.).
- Prazo: informe o prazo fixado no ato; se o ato não fixar, indique o prazo legal aplicável apenas \
se tiver segurança (ex.: CPC art. 218, § 3º - 5 dias, na falta de prazo); processo civil e \
trabalhista contam em dias úteis, salvo exceções. Marque "nao_informado" quando não houver base.
- Datas: a contagem a partir da publicação no DJEN é feita pelo painel; não calcule datas.
- Orientação: prática e acionável, como para a rotina de escritório - o que fazer, o que pedir ao \
cliente, riscos de não agir. Sem explicações básicas.
- Escreva em português do Brasil, com linguagem forense natural e concisa."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "dirigido_ao_cliente": {"type": "string", "enum": ["sim", "nao", "incerto"]},
        "cliente_identificado": {"type": "string",
                                 "description": "Nome e polo da parte cliente, ou vazio se incerto."},
        "justificativa_cliente": {"type": "string"},
        "tipo_ato": {"type": "string", "enum": [
            "despacho", "decisao_interlocutoria", "sentenca", "acordao", "ato_ordinatorio",
            "intimacao_pauta_audiencia", "edital", "citacao", "outro"]},
        "resumo": {"type": "string", "description": "Resumo do ato em 1 a 3 frases."},
        "exige_manifestacao": {"type": "string", "enum": ["sim", "nao", "verificar"]},
        "providencia": {"type": "string",
                        "description": "Ex.: réplica, especificação de provas, recolher custas, "
                                       "recurso, comparecer à audiência, apenas ciência."},
        "prazo_dias": {"type": ["integer", "null"]},
        "prazo_tipo": {"type": "string", "enum": ["uteis", "corridos", "nao_informado"]},
        "base_do_prazo": {"type": "string",
                          "description": "De onde vem o prazo: fixado no ato, dispositivo legal, ou vazio."},
        "urgencia": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "orientacao": {"type": "string"},
        "checklist": {"type": "array", "items": {"type": "string"}},
        "estrutura_peca": {"type": "array", "items": {"type": "string"},
                           "description": "Tópicos da manifestação a preparar; vazio se não houver."},
        "pontos_de_atencao": {"type": "array", "items": {"type": "string"}},
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
    },
    "required": ["dirigido_ao_cliente", "cliente_identificado", "justificativa_cliente", "tipo_ato",
                 "resumo", "exige_manifestacao", "providencia", "prazo_dias", "prazo_tipo",
                 "base_do_prazo", "urgencia", "orientacao", "checklist", "estrutura_peca",
                 "pontos_de_atencao", "confianca"],
    "additionalProperties": False,
}


def _keychain(servico: str) -> str | None:
    if sys.platform != "darwin":
        return None
    r = subprocess.run(["security", "find-generic-password", "-s", servico, "-w"],
                       capture_output=True, text=True, timeout=20)
    return r.stdout.strip() or None if r.returncode == 0 else None


def _chave_api() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or _keychain(KC_SERVICO_API)


def localizar_claude(acfg: dict) -> str | None:
    """Caminho absoluto do Claude Code (o launchd não tem o PATH do Terminal)."""
    cands = [acfg.get("claude_cli") or "", shutil.which("claude") or "",
             str(Path.home() / ".local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    return next((c for c in cands if c and Path(c).exists()), None)


VALORES = {
    "dirigido_ao_cliente": ("sim", "nao", "incerto"), "exige_manifestacao": ("sim", "nao", "verificar"),
    "prazo_tipo": ("uteis", "corridos", "nao_informado"), "urgencia": ("alta", "media", "baixa"),
    "confianca": ("alta", "media", "baixa"),
}


def _normalizar(d: dict) -> dict:
    """Garante todos os campos do esquema (a saída do Claude Code é validada, mas por segurança)."""
    out = {}
    for k, spec in ESQUEMA["properties"].items():
        v = d.get(k)
        if spec.get("type") == "array":
            v = [str(x) for x in v] if isinstance(v, list) else []
        elif k == "prazo_dias":
            v = v if isinstance(v, int) and v > 0 else None
        else:
            v = "" if v is None else str(v)
            if k in VALORES and v not in VALORES[k]:
                v = VALORES[k][-1] if k != "prazo_tipo" else "nao_informado"
            if k == "tipo_ato" and v not in spec["enum"]:
                v = "outro"
        out[k] = v
    return out


def _entrada(reg: dict, cfg: dict) -> str:
    acfg = cfg.get("analise_ia", {})
    clientes = acfg.get("clientes", [])
    oabs = ", ".join(f"{o['numero']}/{o['uf']}" for o in cfg.get("oabs", []))
    dados = {
        "advogado_usuario": {"nome": cfg.get("titular", ""), "oab": oabs},
        "clientes_conhecidos": clientes,
        "processo": reg.get("processo"),
        "tribunal": reg.get("tribunal"),
        "orgao": reg.get("orgao"),
        "classe": reg.get("classe"),
        "tipo_comunicacao": reg.get("tipo"),
        "tipo_documento": reg.get("tipo_documento"),
        "data_disponibilizacao": reg.get("disponibilizacao"),
        "partes_destinatarias": reg.get("partes", []),
        "advogados_destinatarios": reg.get("advogados", []),
    }
    return ("Dados da publicação:\n" + json.dumps(dados, ensure_ascii=False, indent=1) +
            "\n\nTeor da publicação:\n<<<\n" + (reg.get("texto") or "(sem teor)") + "\n>>>")


def analisar_claude_cli(reg: dict, cfg: dict, binario: str) -> dict:
    """Análise pelo Claude Code (assinatura), em modo não interativo e sem ferramentas."""
    acfg = cfg.get("analise_ia", {})
    DIR_TRABALHO.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # força a assinatura
    token = _keychain(KC_SERVICO_OAUTH)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    entrada = (SISTEMA + "\n\nAnalise a publicação abaixo e responda somente no formato estruturado "
               "solicitado.\n\n" + _entrada(reg, cfg))
    cmd = [binario, "-p", "Siga as instruções e analise a publicação recebida pela entrada padrão.",
           "--output-format", "json", "--json-schema", json.dumps(ESQUEMA, ensure_ascii=False),
           "--tools", "", "--disallowedTools", "mcp__*", "--max-turns", "3",
           "--model", acfg.get("modelo_cli", "opus")]
    r = subprocess.run(cmd, input=entrada, capture_output=True, text=True, timeout=int(acfg.get("timeout_s", 300)),
                       cwd=DIR_TRABALHO, env=env)
    try:
        resp = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude Code não respondeu em JSON (código {r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()[:200]}") from None
    dados = resp.get("structured_output")
    if not isinstance(dados, dict):
        texto = str(resp.get("result") or "")
        ini, fim = texto.find("{"), texto.rfind("}")
        if ini < 0 or fim <= ini:
            raise RuntimeError(f"sem análise estruturada: {texto.strip()[:200] or (r.stderr or '').strip()[:200]}")
        dados = json.loads(texto[ini:fim + 1])
    out = _normalizar(dados)
    out["_modelo"] = f"Claude Code ({acfg.get('modelo_cli', 'opus')}, assinatura)"
    out["_gerado_em"] = datetime.now().isoformat(timespec="seconds")
    out["_versao"] = VERSAO_PROMPT
    return out


def analisar(reg: dict, cfg: dict, cliente) -> dict:
    import anthropic

    acfg = cfg.get("analise_ia", {})
    modelo = acfg.get("modelo", "claude-opus-5-5")
    pedido = dict(
        model=modelo,
        max_tokens=16000,
        system=SISTEMA,
        output_config={"effort": acfg.get("esforco", "medium"),
                       "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": _entrada(reg, cfg)}],
    )
    if acfg.get("fallback_recusa", True):
        # se o filtro de segurança recusar, o próprio servidor tenta um modelo alternativo
        resp = cliente.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                            fallbacks="default", **pedido)
    else:
        resp = cliente.messages.create(**pedido)
    if resp.stop_reason == "refusal":
        raise RuntimeError("análise recusada pelo modelo")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("resposta incompleta (limite de tokens)")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    out = json.loads(texto)
    out["_modelo"] = resp.model
    out["_gerado_em"] = datetime.now().isoformat(timespec="seconds")
    out["_versao"] = VERSAO_PROMPT
    return out


def analisar_pendentes(registros: dict, cfg: dict, log) -> dict:
    """Analisa as comunicações ainda sem análise. Retorna {id: analise}."""
    analises: dict = {}
    try:
        analises = json.loads(ARQ_ANALISES.read_text(encoding="utf-8"))
    except Exception:
        pass
    # descarta análises de comunicações que saíram da janela
    analises = {k: v for k, v in analises.items() if k in registros}

    acfg = cfg.get("analise_ia", {})
    if not acfg.get("ativo"):
        return analises
    pendentes = [r for r in sorted(registros.values(), key=lambda r: r["disponibilizacao"], reverse=True)
                 if r["id"] not in analises or analises[r["id"]].get("_versao") != VERSAO_PROMPT]
    if not pendentes:
        return analises

    if acfg.get("motor", "claude_cli") == "claude_cli":
        binario = localizar_claude(acfg)
        if not binario:
            log("Análise IA: Claude Code não encontrado. Rode configurar_analise_ia.command.")
            return analises
        limite = int(acfg.get("max_por_execucao", 10))
        feitas = erros = 0
        for reg in pendentes[:limite]:
            try:
                analises[reg["id"]] = analisar_claude_cli(reg, cfg, binario)
                feitas += 1
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                erros += 1
                msg = str(e)
                log(f"Análise IA {reg.get('processo')}: {msg[:200]}")
                if erros >= 2 or any(x in msg.lower() for x in ("login", "auth", "limit", "usage")):
                    break  # sem login, limite da assinatura ou instabilidade: tenta na próxima execução
            ARQ_ANALISES.parent.mkdir(exist_ok=True)
            ARQ_ANALISES.write_text(json.dumps(analises, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"Análise IA (Claude Code): {feitas} analisada(s), {erros} erro(s), "
            f"{max(0, len(pendentes) - feitas)} pendente(s).")
        return analises

    chave = _chave_api()
    if not chave:
        log("Análise IA: chave da API não encontrada (Chaves do macOS: painel-anthropic-api).")
        return analises
    try:
        import anthropic
    except ImportError:
        log("Análise IA: pacote 'anthropic' não instalado. Rode atualizar_codigo.command.")
        return analises

    cliente = anthropic.Anthropic(api_key=chave, max_retries=3, timeout=180)
    limite = int(acfg.get("max_por_execucao", 30))
    feitas = erros = 0
    for reg in pendentes[:limite]:
        try:
            analises[reg["id"]] = analisar(reg, cfg, cliente)
            feitas += 1
        except anthropic.AuthenticationError:
            log("Análise IA: chave da API inválida.")
            break
        except anthropic.RateLimitError:
            log("Análise IA: limite de uso atingido; continua na próxima execução.")
            break
        except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError, ValueError) as e:
            erros += 1
            log(f"Análise IA {reg.get('processo')}: {e}")
            if erros >= 3:
                break
        ARQ_ANALISES.parent.mkdir(exist_ok=True)
        ARQ_ANALISES.write_text(json.dumps(analises, ensure_ascii=False, indent=1), encoding="utf-8")
    if feitas or erros:
        log(f"Análise IA: {feitas} publicação(ões) analisada(s), {erros} erro(s), "
            f"{max(0, len(pendentes) - feitas)} pendente(s).")
    ARQ_ANALISES.parent.mkdir(exist_ok=True)
    ARQ_ANALISES.write_text(json.dumps(analises, ensure_ascii=False, indent=1), encoding="utf-8")
    return analises
