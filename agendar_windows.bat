@echo off
chcp 65001 >nul
REM Agenda o coletor do Painel DJEN para rodar a cada 1 hora (Agendador de Tarefas do Windows).
REM Execute uma vez com dois cliques. Para remover: schtasks /delete /tn "Painel DJEN" /f
set PASTA=%~dp0
where pythonw >nul 2>nul && (set PY=pythonw) || (set PY=python)
"%PY%" "%PASTA%djen_painel.py"
schtasks /create /tn "Painel DJEN" /sc hourly /mo 1 /tr "\"%PY%\" \"%PASTA%djen_painel.py\"" /f
if %errorlevel%==0 (
  echo.
  echo Agendamento criado: o painel sera atualizado a cada hora.
  echo Abra o arquivo: %PASTA%painel.html
  start "" "%PASTA%painel.html"
) else (
  echo Falha ao criar o agendamento.
)
pause
