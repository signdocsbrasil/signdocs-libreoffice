@echo off
rem ===================================================================
rem  SignDocs Brasil para LibreOffice - teste em Homologacao (Windows)
rem
rem  Instala a extensao num perfil descartavel e abre o Writer.
rem  Roda AO LADO do seu LibreOffice normal: o seu perfil, as suas
rem  extensoes e os seus documentos abertos nao sao tocados, e nao e
rem  preciso fechar nada. Para desfazer, apague a pasta do perfil.
rem
rem  Uso: coloque este arquivo na MESMA PASTA do .oxt e clique duas
rem  vezes. Ou, no Prompt de Comando:  try-it.cmd
rem ===================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- 0. qual modulo abrir -----------------------------------------
rem  Os quatro modulos sao caminhos diferentes: o Addons.xcu cita os quatro
rem  no Context, e o intake.py mapeia cada um ao seu proprio filtro de
rem  exportacao para PDF. Um modulo faltando em uma das listas falha de um
rem  jeito que os outros nunca mostram.
rem
rem    try-it.cmd            Writer (padrao)
rem    try-it.cmd --calc     ...ou --impress, --draw, --writer
rem    try-it.cmd --all      os quatro de uma vez, no mesmo perfil
set "MODULES=--writer"
set "LABEL=Writer"
if /i "%~1"=="--calc"    set "MODULES=--calc"    & set "LABEL=Calc"
if /i "%~1"=="--impress" set "MODULES=--impress" & set "LABEL=Impress"
if /i "%~1"=="--draw"    set "MODULES=--draw"    & set "LABEL=Draw"
if /i "%~1"=="--writer"  set "MODULES=--writer"  & set "LABEL=Writer"
if /i "%~1"=="--all"     set "MODULES=--writer --calc --impress --draw" & set "LABEL=Writer, Calc, Impress e Draw"

rem  Impresso depois do bloco acima, e nao antes: LABEL so existe a partir
rem  daqui, e um echo mais cedo saia como "Abrindo:" sem nada depois.
echo.
echo   SignDocs Brasil - extensao para LibreOffice
echo   Ambiente: HOMOLOGACAO (hml)
echo   Abrindo:  %LABEL%
echo.

rem --- 1. localizar o LibreOffice ------------------------------------
rem  unopkg.COM e nao unopkg.EXE: no Windows o .exe retorna na hora e o
rem  script seguiria antes de a instalacao terminar. O .com e a versao
rem  de console, que espera.
rem  Nao usar um bloco for(...) aqui: %ProgramFiles(x86)% contem parenteses,
rem  que fecham o bloco cedo e quebram o script de um jeito silencioso.
set "LO="
if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "LO=%ProgramFiles%\LibreOffice\program"
if not defined LO if exist "%ProgramW6432%\LibreOffice\program\soffice.exe" set "LO=%ProgramW6432%\LibreOffice\program"
if not defined LO if exist "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe" set "LO=%ProgramFiles(x86)%\LibreOffice\program"
if not defined LO for %%P in (soffice.exe) do if not defined LO if not "%%~dp$PATH:P"=="" set "LO=%%~dp$PATH:P"
if defined LO if "%LO:~-1%"=="\" set "LO=%LO:~0,-1%"
if not defined LO (
  echo   [ERRO] LibreOffice nao encontrado.
  echo   Instale em https://pt-br.libreoffice.org/baixe-ja/ e rode de novo.
  echo.
  pause
  exit /b 1
)
echo   LibreOffice: %LO%

rem --- 2. localizar o .oxt -------------------------------------------
set "OXT="
for %%F in ("signdocs-brasil-*.oxt") do set "OXT=%%~fF"
if not defined OXT (
  echo   [ERRO] Nenhum arquivo signdocs-brasil-*.oxt nesta pasta:
  echo          %CD%
  echo   Coloque o .oxt junto deste script.
  echo.
  pause
  exit /b 1
)
echo   Extensao:    %OXT%

rem --- 3. perfil descartavel -----------------------------------------
set "SDPROFILE=%TEMP%\lo-signdocs-try"
if /i "%~1"=="--reset" (
  echo   Apagando perfil anterior...
  rmdir /s /q "%SDPROFILE%" 2>nul
)
if not exist "%SDPROFILE%\user" mkdir "%SDPROFILE%\user" 2>nul

rem  A UNO precisa de uma URL file:/// com barras normais:
rem  C:\Users\...  ->  file:///C:/Users/...
set "PROFILE_URL=file:///%SDPROFILE:\=/%"

rem --- 4. apontar para HOMOLOGACAO antes de abrir ---------------------
rem  Mesmo arquivo que a tela de Configuracoes grava. So cria se nao existir:
rem  sobrescrever apagaria o refresh token e exigiria login a cada execucao.
if not exist "%SDPROFILE%\user\signdocs.json" (
  > "%SDPROFILE%\user\signdocs.json" echo {"signdocs.stage": "hml"}
  echo   Ambiente definido como homologacao.
) else (
  echo   Perfil ja existe - mantendo a sessao anterior.
  echo   ^(use  try-it.cmd --reset  para comecar do zero^)
)

rem --- 5. instalar ----------------------------------------------------
echo.
echo   Instalando...
"%LO%\unopkg.com" add -f -env:UserInstallation=%PROFILE_URL% "%OXT%"
if errorlevel 1 (
  echo.
  echo   [ERRO] Falha ao instalar a extensao. Saida acima.
  echo.
  pause
  exit /b 1
)
echo   OK.

rem --- 6. abrir -------------------------------------------------------
echo.
echo   Abrindo: %LABEL%
echo.
echo     Menu:    Ferramentas ^> Suplementos ^> SignDocs Brasil
echo     Barra:   Exibir ^> Barras de ferramentas ^> Add-On 1
echo.
echo     1. Digite algo no documento - e ele que sera assinado.
echo     2. Ferramentas ^> Suplementos ^> SignDocs Brasil ^> Enviar para assinatura
echo     3. Clique em Conectar. O navegador abre em login-hml.signdocs.com.br
echo     4. Entre com a sua conta de HOMOLOGACAO (nao a de producao)
echo     5. Volte ao Writer - a janela segue sozinha
echo.
echo     Perfil de teste: %SDPROFILE%
echo     (apague essa pasta para desfazer tudo)
echo.

start "" "%LO%\soffice.exe" -env:UserInstallation=%PROFILE_URL% --norestore %MODULES%

echo   Pronto. Pode fechar esta janela.
echo.
pause
endlocal
