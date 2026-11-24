#!/bin/bash
# Remove o agendamento e a senha do certificado das Chaves do macOS (não apaga a pasta).
PLIST="$HOME/Library/LaunchAgents/br.painel-djen.coletor.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null; rm -f "$PLIST"
security delete-generic-password -s painel-eproc-certificado >/dev/null 2>&1
security delete-generic-password -s painel-eproc-totp >/dev/null 2>&1
echo "Agendamento e senhas removidos. Apague a pasta 'certificado' se não for mais usar."
read -r -p "Tecle Enter para fechar."
