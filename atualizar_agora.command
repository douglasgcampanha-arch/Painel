#!/bin/bash
cd "$(dirname "$0")"
.venv/bin/python djen_painel.py
if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8765/; then open "http://127.0.0.1:8765"; else open painel.html; fi
