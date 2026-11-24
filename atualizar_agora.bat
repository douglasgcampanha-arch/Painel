@echo off
chcp 65001 >nul
python "%~dp0djen_painel.py"
start "" "%~dp0painel.html"
