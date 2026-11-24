#!/bin/bash
cd "$(dirname "$0")"
.venv/bin/python djen_painel.py
open painel.html
