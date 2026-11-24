#!/bin/bash
# Ativa a análise das publicações com o Claude (API da Anthropic).
# A chave da API fica nas Chaves do macOS (serviço painel-anthropic-api), nunca em arquivo.
cd "$(dirname "$0")"
echo "== Análise das publicações com IA =="
echo "Crie a chave em https://console.anthropic.com (API Keys) e cole abaixo duas vezes."
echo "(O uso da API é cobrado à parte da assinatura do Claude.)"
security add-generic-password -U -s painel-anthropic-api -a "$USER" -w
echo
echo "Informe os nomes dos seus clientes (um por linha; Enter em branco para terminar)."
echo "Isso ajuda a identificar se a publicação é para o seu cliente. Pode deixar em branco."
CLIENTES=()
while IFS= read -r -p "> " L && [ -n "$L" ]; do CLIENTES+=("$L"); done
printf '%s\n' "${CLIENTES[@]}" > dados/.clientes_tmp 2>/dev/null || { mkdir -p dados; printf '%s\n' "${CLIENTES[@]}" > dados/.clientes_tmp; }
.venv/bin/python - <<'PY'
import json, pathlib
import djen_painel
cfg = djen_painel.carregar_config()
novos = [l.strip() for l in pathlib.Path("dados/.clientes_tmp").read_text(encoding="utf-8").splitlines() if l.strip()]
pathlib.Path("dados/.clientes_tmp").unlink()
a = cfg.setdefault("analise_ia", {})
a["ativo"] = True
a["clientes"] = sorted(set(a.get("clientes", []) + novos))
pathlib.Path("config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Análise IA ativada. Clientes cadastrados: {len(a['clientes'])}")
PY
.venv/bin/pip install -q --only-binary=:all: -r requirements.txt
echo "Analisando as publicações dos últimos 7 dias (pode levar alguns minutos)..."
.venv/bin/python djen_painel.py
open painel.html
read -r -p "Tecle Enter para fechar."
