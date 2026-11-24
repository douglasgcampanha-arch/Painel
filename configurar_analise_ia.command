#!/bin/bash
# Ativa a análise das publicações usando o Claude Code com a SUA ASSINATURA do Claude
# (sem chave de API). Consome o limite de uso da assinatura.
cd "$(dirname "$0")"
echo "== Análise das publicações com o Claude Code (assinatura) =="

CLAUDE="$(command -v claude || true)"
[ -z "$CLAUDE" ] && [ -x "$HOME/.local/bin/claude" ] && CLAUDE="$HOME/.local/bin/claude"
if [ -z "$CLAUDE" ]; then
  echo "Claude Code não encontrado. Instalando pelo instalador oficial..."
  curl -fsSL https://claude.ai/install.sh | bash
  CLAUDE="$HOME/.local/bin/claude"
fi
[ -x "$CLAUDE" ] || { echo "Não foi possível localizar o Claude Code. Instale e rode de novo."; exit 1; }
echo "Claude Code: $CLAUDE"

if ! env -u ANTHROPIC_API_KEY "$CLAUDE" auth status >/dev/null 2>&1; then
  echo "Faça login com a sua conta do Claude (abre o navegador)..."
  env -u ANTHROPIC_API_KEY "$CLAUDE" auth login
fi

echo "Testando..."
RESP="$(cd /tmp && env -u ANTHROPIC_API_KEY "$CLAUDE" -p "Responda apenas: OK" --output-format json --tools "" --max-turns 1 2>&1)"
if ! printf '%s' "$RESP" | grep -q '"result"'; then
  echo "O teste falhou:"; printf '%s\n' "$RESP" | head -5; exit 1
fi
echo "Claude Code funcionando com a assinatura."

echo
echo "Informe os nomes dos seus clientes (um por linha; Enter em branco para terminar)."
echo "Ajuda a identificar se a publicação é para o seu cliente. Pode deixar em branco."
mkdir -p dados; : > dados/.clientes_tmp
while IFS= read -r -p "> " L && [ -n "$L" ]; do printf '%s\n' "$L" >> dados/.clientes_tmp; done

CLAUDE_PATH="$CLAUDE" .venv/bin/python - <<'PY'
import json, os, pathlib
import djen_painel
cfg = djen_painel.carregar_config()
tmp = pathlib.Path("dados/.clientes_tmp")
novos = [l.strip() for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
tmp.unlink()
a = cfg.setdefault("analise_ia", {})
a.update({"ativo": True, "motor": "claude_cli", "claude_cli": os.environ["CLAUDE_PATH"]})
a["clientes"] = sorted(set(a.get("clientes", []) + novos))
pathlib.Path("config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Análise ativada (Claude Code). Clientes cadastrados: {len(a['clientes'])}")
PY

echo
echo "Analisando as publicações mais recentes (até 10 por execução; as demais nas próximas horas)..."
.venv/bin/python djen_painel.py
open painel.html
echo
echo "Se o agendamento automático não conseguir usar o login (aviso no log), rode:"
echo "  $CLAUDE setup-token"
echo "e guarde o token com:  security add-generic-password -U -s painel-claude-oauth -a \"\$USER\" -w"
read -r -p "Tecle Enter para fechar."
