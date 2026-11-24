#!/bin/bash
# Abre o navegador do robô para validar o 2FA do eproc TJSP e liberar este dispositivo.
cd "$(dirname "$0")"
echo "Uma janela do navegador vai abrir. Digite o código do autenticador e mantenha marcada"
echo "a opção 'Não usar o 2FA neste dispositivo e navegador'."
.venv/bin/python eproc_tjsp.py --interativo && .venv/bin/python djen_painel.py
open painel.html
read -r -p "Tecle Enter para fechar."
