"""
Módulo DataJud - acompanhamento de movimentações processuais pela API Pública do
DataJud (CNJ), que recebe os dados de todos os tribunais, independentemente do
sistema de origem (PJe, eproc, e-SAJ, Projudi etc.).

Documentação: https://datajud-wiki.cnj.jus.br/api-publica/
Uso sujeito ao Termo de Uso da API Pública (uso legal e não comercial).
Observações:
- A API não traz nomes de partes/advogados nem o teor de decisões: apenas metadados
  (classe, órgão, assuntos) e a lista de movimentos codificados (Tabelas Processuais Unificadas).
- Os tribunais enviam os dados em lotes; há defasagem de horas a dias em relação ao sistema.
- Processos sigilosos não são retornados.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

API_HOST = "https://api-publica.datajud.cnj.jus.br"
# Chave pública divulgada em https://datajud-wiki.cnj.jus.br/api-publica/acesso
# (o CNJ pode trocá-la a qualquer momento; se mudar, atualize "datajud_chave" no config.json)
CHAVE_PADRAO = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="

# Código TR (Res. CNJ 65/2008) -> UF, para Justiça Estadual (J=8) e Eleitoral (J=6)
_UF_POR_TR = {
    "01": "ac", "02": "al", "03": "ap", "04": "am", "05": "ba", "06": "ce", "07": "dft",
    "08": "es", "09": "go", "10": "ma", "11": "mt", "12": "ms", "13": "mg", "14": "pa",
    "15": "pb", "16": "pr", "17": "pe", "18": "pi", "19": "rj", "20": "rn", "21": "rs",
    "22": "ro", "23": "rr", "24": "sc", "25": "se", "26": "sp", "27": "to",
}
_TJM = {"13": "tjmmg", "21": "tjmrs", "26": "tjmsp"}


def so_digitos(numero: str) -> str:
    return re.sub(r"\D", "", numero or "")


def mascara(n: str) -> str:
    n = so_digitos(n)
    if len(n) != 20:
        return n
    return f"{n[:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:]}"


def alias_tribunal(numero: str) -> str | None:
    """Deduz o índice da API (ex.: api_publica_tjsp) a partir do número CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO)."""
    n = so_digitos(numero)
    if len(n) != 20:
        return None
    j, tr = n[13], n[14:16]
    if j == "8" and tr in _UF_POR_TR:
        return "tj" + _UF_POR_TR[tr]
    if j == "5":
        return "tst" if tr == "00" else f"trt{int(tr)}"
    if j == "4" and tr != "00":
        return f"trf{int(tr)}"
    if j == "6":
        return "tse" if tr == "00" else ("tre-" + _UF_POR_TR[tr] if tr in _UF_POR_TR else None)
    if j == "3":
        return "stj"
    if j == "7":
        return "stm"
    if j == "9":
        return _TJM.get(tr)
    return None  # STF (J=1) e CNJ (J=2) não estão na API pública


def _buscar(alias: str, numero: str, chave: str, log) -> list[dict]:
    url = f"{API_HOST}/api_publica_{alias}/_search"
    corpo = json.dumps({"size": 10, "query": {"match": {"numeroProcesso": so_digitos(numero)}}}).encode()
    req = urllib.request.Request(url, data=corpo, method="POST", headers={
        "Authorization": f"APIKey {chave}",
        "Content-Type": "application/json",
        "User-Agent": "PainelDJEN/1.0 (uso pessoal)",
    })
    espera = 10
    for tentativa in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                dados = json.loads(r.read().decode("utf-8"))
            return [h.get("_source", {}) for h in dados.get("hits", {}).get("hits", [])]
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(
                    "DataJud recusou a chave pública (HTTP %d). Confira a chave vigente em "
                    "datajud-wiki.cnj.jus.br/api-publica/acesso e atualize 'datajud_chave' no config.json." % e.code
                ) from None
            if e.code in (429, 500, 502, 503, 504) and tentativa < 4:
                log(f"DataJud HTTP {e.code} ({mascara(numero)}); nova tentativa em {espera}s")
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError(f"DataJud HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if tentativa < 4:
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError(f"Sem conexão com o DataJud: {e}") from None
    return []


def _complementos(mov: dict) -> str:
    partes = []
    for c in mov.get("complementosTabelados") or []:
        nome = c.get("nome")
        if nome:
            partes.append(str(nome))
    return "; ".join(partes)


def atualizar_carteira(carteira: dict, numeros_djen: dict, cfg: dict, log) -> dict:
    """Atualiza a carteira (dict numero -> registro) consultando o DataJud.
    numeros_djen: {numero_digitos: tribunal_sigla} vindos das intimações.
    Retorna resumo {consultados, novas_movimentacoes, erros}."""
    agora = datetime.now()
    agora_iso = agora.isoformat(timespec="seconds")
    chave = cfg.get("datajud_chave") or CHAVE_PADRAO
    intervalo = timedelta(hours=float(cfg.get("datajud_intervalo_horas", 6)))
    limite = int(cfg.get("datajud_max_por_execucao", 40))

    # 1) incorpora processos novos (DJEN + lista manual)
    manuais = {so_digitos(n): "manual" for n in cfg.get("processos", [])}
    for n, origem in [*((k, "djen") for k in numeros_djen), *manuais.items()]:
        if len(n) != 20:
            continue
        reg = carteira.setdefault(n, {
            "numero": mascara(n), "origem": origem, "adicionado_em": agora_iso,
            "ultima_consulta": "", "erro": "", "instancias": [], "movimentos": [],
        })
        if origem == "manual":
            reg["origem"] = "manual"

    # 2) escolhe quem consultar nesta execução (mais antigos primeiro)
    def vencido(r):
        if not r["ultima_consulta"]:
            return True
        return agora - datetime.fromisoformat(r["ultima_consulta"]) >= intervalo

    fila = sorted((r for r in carteira.values() if vencido(r)), key=lambda r: r["ultima_consulta"] or "")
    fila = fila[:limite]

    resumo = {"consultados": 0, "novas_movimentacoes": 0, "erros": 0}
    for i, reg in enumerate(fila):
        n = so_digitos(reg["numero"])
        alias = alias_tribunal(n)
        if not alias:
            reg["erro"] = "Tribunal não disponível na API pública do DataJud"
            reg["ultima_consulta"] = agora_iso
            continue
        try:
            fontes = _buscar(alias, n, chave, log)
        except RuntimeError as e:
            reg["erro"] = str(e)
            resumo["erros"] += 1
            log(f"DataJud {reg['numero']}: {e}")
            if "chave" in str(e):
                break  # chave inválida: não adianta continuar
            continue
        reg["ultima_consulta"] = agora_iso
        reg["alias"] = alias
        resumo["consultados"] += 1
        if not fontes:
            reg["erro"] = "Não localizado no DataJud (pode ser sigiloso, recente ou ainda não enviado pelo tribunal)"
            continue
        reg["erro"] = ""

        primeira_carga = not reg["movimentos"]
        vistos = {m["chave"] for m in reg["movimentos"]}
        instancias = []
        for s in fontes:
            grau = s.get("grau", "")
            instancias.append({
                "grau": grau,
                "tribunal": s.get("tribunal", ""),
                "sistema": (s.get("sistema") or {}).get("nome", ""),
                "formato": (s.get("formato") or {}).get("nome", ""),
                "classe": (s.get("classe") or {}).get("nome", ""),
                "orgao": (s.get("orgaoJulgador") or {}).get("nome", ""),
                "assuntos": [a.get("nome", "") for a in (s.get("assuntos") or []) if isinstance(a, dict)],
                "ajuizamento": (s.get("dataAjuizamento") or "")[:10],
                "atualizado_tribunal": s.get("dataHoraUltimaAtualizacao", ""),
            })
            for m in s.get("movimentos") or []:
                k = f"{grau}|{m.get('codigo', '')}|{m.get('dataHora', '')}|{m.get('nome', '')}"
                if k in vistos:
                    continue
                vistos.add(k)
                reg["movimentos"].append({
                    "chave": k,
                    "data": m.get("dataHora", ""),
                    "nome": m.get("nome", ""),
                    "complemento": _complementos(m),
                    "grau": grau,
                    "nova_em": "" if primeira_carga else agora_iso,
                })
                if not primeira_carga:
                    resumo["novas_movimentacoes"] += 1
        reg["instancias"] = instancias
        reg["movimentos"].sort(key=lambda m: m["data"], reverse=True)
        if i < len(fila) - 1:
            time.sleep(1.0)  # uso moderado da API pública

    return resumo
