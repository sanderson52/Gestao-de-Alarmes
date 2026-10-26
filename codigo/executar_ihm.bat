@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
for %%P in ("%LOCALAPPDATA%\Python\bin\python.exe" python py) do (
    if not defined PY (
        "%%~P" -c "import sys" >nul 2>nul && set "PY=%%~P"
    )
)
if not defined PY (
    echo Python nao encontrado. Instale o Python 3.9+ marcando "Add python.exe to PATH"
    echo ou desative os "Aliases de execucao do aplicativo" do python em Configuracoes do Windows.
    pause
    exit /b 1
)
echo Abrindo a IHM em http://localhost:8000  (feche esta janela ou Ctrl+C para encerrar)
"%PY%" servidor_ihm.py
pause
