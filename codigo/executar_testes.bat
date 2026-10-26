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
echo === 1/3 Demonstracao original da P1 ===
"%PY%" automacao.py
echo.
echo === 2/3 Testes automatizados (unittest) ===
"%PY%" -m unittest -v test_automacao.py
echo.
echo === 3/3 Comparativo da simulacao (cenario A x B) ===
"%PY%" cenario_compressor.py
echo.
pause
