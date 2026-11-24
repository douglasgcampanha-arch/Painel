#!/bin/bash
# Baixa a versão mais recente do Painel pelo Git, sem tocar em config.json,
# certificado/, dados/ e .venv/ (todos fora do Git).
cd "$(dirname "$0")"
RAMO="claude/gifted-volta-vxo3s6"
git fetch -q origin "$RAMO" || { echo "Falha ao baixar. Rode: gh auth login"; exit 1; }
git reset -q --hard FETCH_HEAD
echo "Código atualizado: $(git log -1 --format='%h %s')"
.venv/bin/python djen_painel.py
open painel.html
