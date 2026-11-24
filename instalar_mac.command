#!/bin/bash
# Painel DJEN - instalação no macOS (dois cliques no Finder).
# Cria o ambiente Python, instala o navegador do robô, guarda a senha do certificado
# nas Chaves do macOS e agenda a atualização a cada 1 hora (launchd).
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "== Painel DJEN - instalação no Mac =="
echo "Pasta: $DIR"

case "$DIR" in
  */Documents/*|*/Desktop/*|*/Downloads/*|*"Mobile Documents"*|*/Documentos/*|*"Mesa"*)
    echo
    echo "ATENÇÃO: mova a pasta para fora de Documentos, Mesa, Downloads ou iCloud"
    echo "(sugestão: $HOME/PainelDJEN). O macOS bloqueia tarefas automáticas nessas pastas."
    exit 1;;
esac

# O Playwright precisa de Python 3.9 a 3.13 (versões mais novas ainda não têm todos os componentes prontos).
PY=""
for c in python3.13 python3.12 python3.11 \
         /opt/homebrew/opt/python@3.13/bin/python3.13 /opt/homebrew/opt/python@3.12/bin/python3.12 \
         /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys; print(sys.version_info[1] if sys.version_info[0]==3 else 0)')
    if [ "$v" -ge 9 ] && [ "$v" -le 13 ]; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "Nenhum Python compatível (3.9 a 3.13) encontrado."
  if command -v brew >/dev/null; then
    echo "Instalando Python 3.13 pelo Homebrew..."
    brew install python@3.13
    PY=/opt/homebrew/opt/python@3.13/bin/python3.13
  else
    echo "Instale o Python 3.13 em https://www.python.org/downloads/macos/ e rode de novo."
    exit 1
  fi
fi
echo "Usando $PY ($("$PY" --version))"

echo; echo "1/4 Preparando o ambiente Python..."
rm -rf .venv
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q --only-binary=:all: -r requirements.txt
.venv/bin/python -m playwright install chromium

[ -f config.json ] || cp config.exemplo.json config.json
USAR_EPROC=n
echo
read -r -p "2/4 Configurar o eproc TJSP com o certificado digital A1 agora? (s/n) " USAR_EPROC
if [[ "$USAR_EPROC" =~ ^[sS] ]]; then
  read -r -p "Arraste o arquivo do certificado (.pfx ou .p12) para esta janela e tecle Enter: " PFX
  PFX="$(printf '%s' "$PFX" | sed -e 's/[[:space:]]*$//' -e "s/^['\"]//" -e "s/['\"]\$//" -e 's/\\\(.\)/\1/g')"
  if [ ! -f "$PFX" ]; then echo "Arquivo não encontrado: $PFX"; exit 1; fi
  mkdir -p certificado && chmod 700 certificado
  cp "$PFX" certificado/certificado.pfx && chmod 600 certificado/certificado.pfx
  echo
  echo "Digite a SENHA do certificado (duas vezes). Ela fica nas Chaves do macOS, não em arquivo:"
  security add-generic-password -U -s painel-eproc-certificado -a "$USER" -w
  .venv/bin/python - <<'PY'
import json, pathlib
c = pathlib.Path("config.json"); cfg = json.loads(c.read_text(encoding="utf-8"))
cfg.setdefault("eproc_tjsp", {}).update({"ativo": True, "certificado_pfx": "certificado/certificado.pfx"})
c.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("config.json: eproc_tjsp ativado.")
PY
fi

echo; echo "3/4 Agendando a atualização a cada 1 hora..."
PLIST="$HOME/Library/LaunchAgents/br.painel-djen.coletor.plist"
mkdir -p "$HOME/Library/LaunchAgents" dados
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>br.painel-djen.coletor</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>$DIR/djen_painel.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/dados/launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/dados/launchd.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Agendado (launchd: br.painel-djen.coletor)."

if [[ "$USAR_EPROC" =~ ^[sS] ]]; then
  echo; echo "4/4 Primeiro acesso ao eproc: uma janela do navegador vai abrir."
  echo "    Digite o código do autenticador e mantenha marcada 'Não usar o 2FA neste dispositivo e navegador'."
  .venv/bin/python eproc_tjsp.py --interativo || echo "Primeiro acesso não concluído; rode eproc_primeiro_acesso.command depois."
fi

.venv/bin/python djen_painel.py || true
open painel.html
echo; echo "Pronto. O painel será atualizado a cada hora. Mantenha o Mac sem repouso automático."
read -r -p "Tecle Enter para fechar."
