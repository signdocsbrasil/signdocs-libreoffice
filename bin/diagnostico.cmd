@echo off
rem ===================================================================
rem  SignDocs Brasil - diagnostico (Windows)
rem
rem  Rode isto se o try-it.cmd falhar, ou se o login nao completar.
rem  Nao instala nada e nao precisa do LibreOffice aberto.
rem
rem  Gera  signdocs-diagnostico.json  nesta pasta. Mande esse arquivo.
rem ===================================================================

setlocal
cd /d "%~dp0"

echo.
echo   SignDocs Brasil - diagnostico
echo.

rem  Usa o Python do PROPRIO LibreOffice de proposito: e o interpretador
rem  que a extensao usa de verdade, e no Windows ele tem o seu proprio
rem  OpenSSL. Testar com outro Python nao provaria nada sobre o TLS.
set "PY="
if exist "%ProgramFiles%\LibreOffice\program\python.exe" set "PY=%ProgramFiles%\LibreOffice\program\python.exe"
if not defined PY if exist "%ProgramW6432%\LibreOffice\program\python.exe" set "PY=%ProgramW6432%\LibreOffice\program\python.exe"
if not defined PY if exist "%ProgramFiles(x86)%\LibreOffice\program\python.exe" set "PY=%ProgramFiles(x86)%\LibreOffice\program\python.exe"

if defined PY (
  echo   Python do LibreOffice: %PY%
) else (
  echo   [aviso] Python do LibreOffice nao encontrado - usando o Python
  echo           do sistema. O resultado do TLS pode nao refletir o que
  echo           a extensao ve.
  set "PY=python"
)

echo.
"%PY%" "%~dp0diagnostico.py" --stage hml
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Nenhum problema encontrado nesta maquina.
) else (
  echo   Foram encontrados problemas - veja a lista acima.
)
echo   Mande o arquivo signdocs-diagnostico.json desta pasta.
echo.
pause
endlocal
