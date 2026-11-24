#!/bin/bash
# Gera um arquivo com a ESTRUTURA das telas do eproc (sem números de processo nem nomes),
# para ajuste fino do robô. Envie o arquivo dados/eproc_diagnostico/estrutura.json.
cd "$(dirname "$0")"
.venv/bin/python eproc_tjsp.py --interativo --diagnostico
open dados/eproc_diagnostico
read -r -p "Tecle Enter para fechar."
