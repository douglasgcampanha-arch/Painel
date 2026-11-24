#!/bin/bash
# Integração Painel -> Astrea: ativa o servidor local do painel, faz o login do robô no
# Astrea e grava o diagnóstico das telas (estrutura, sem dados) para calibração.
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "== Integração com o Astrea =="
read -r -p "Endereço de login do Astrea [https://astrea.net.br]: " URL
URL="${URL:-https://astrea.net.br}"
ASTREA_URL="$URL" .venv/bin/python - <<'PY'
import json, os, pathlib, djen_painel
cfg = djen_painel.carregar_config()
cfg.setdefault("astrea", {}).update({"ativo": True, "url": os.environ["ASTREA_URL"]})
pathlib.Path("config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("config.json: Astrea ativado.")
PY

echo; echo "1/3 Servidor local do painel (http://127.0.0.1:8765)..."
PLIST="$HOME/Library/LaunchAgents/br.painel-djen.servidor.plist"
mkdir -p "$HOME/Library/LaunchAgents" dados
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>br.painel-djen.servidor</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>$DIR/servidor_painel.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/dados/servidor.log</string>
  <key>StandardErrorPath</key><string>$DIR/dados/servidor.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Servidor ativo."

echo; echo "2/3 Login do robô no Astrea: uma janela vai abrir."
.venv/bin/python astrea.py --login

echo; echo "3/3 Diagnóstico das telas: siga as instruções (não salve nada no Astrea)."
.venv/bin/python astrea.py --diagnostico
.venv/bin/python djen_painel.py >/dev/null 2>&1
open "http://127.0.0.1:8765"
open dados/astrea_diagnostico
echo
echo "Envie o arquivo dados/astrea_diagnostico/estrutura.json para calibrar o robô."
read -r -p "Tecle Enter para fechar."
