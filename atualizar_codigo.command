#!/bin/bash
# Baixa a versão mais recente do Painel pelo Git, sem tocar em config.json,
# certificado/, dados/ e .venv/ (todos fora do Git).
cd "$(dirname "$0")"
RAMO="claude/gifted-volta-vxo3s6"
git fetch -q origin "$RAMO" || { echo "Falha ao baixar. Rode: gh auth login"; exit 1; }
git reset -q --hard FETCH_HEAD
echo "Código atualizado: $(git log -1 --format='%h %s')"
.venv/bin/pip install -q --only-binary=:all: -r requirements.txt
# reinicia o servidor local do painel, se instalado
launchctl kickstart -k "gui/$(id -u)/br.painel-djen.servidor" 2>/dev/null || true
.venv/bin/python djen_painel.py
if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8765/; then open "http://127.0.0.1:8765"; else open painel.html; fi
