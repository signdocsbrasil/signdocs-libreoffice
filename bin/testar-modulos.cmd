@echo off
rem ===================================================================
rem  SignDocs Brasil - testar os quatro modulos do LibreOffice
rem
rem  try-it.cmd aceita --calc, --impress e --draw, mas um testador abre
rem  o arquivo com dois cliques, e dois cliques nao passam argumento
rem  nenhum. Sem este menu os outros tres modulos ficariam inalcancaveis
rem  para quem nao usa o Prompt de Comando.
rem
rem  Uso: clique duas vezes neste arquivo e escolha o modulo.
rem ===================================================================

setlocal
cd /d "%~dp0"

echo.
echo   SignDocs Brasil - qual modulo voce quer testar?
echo.
echo     1  Writer    (documento de texto)
echo     2  Calc      (planilha)
echo     3  Impress   (apresentacao)
echo     4  Draw      (desenho)
echo     5  Todos os quatro de uma vez
echo.
echo   Em cada um: Ferramentas ^> Suplementos ^> SignDocs Brasil
echo.

rem  choice.exe existe em todo Windows moderno e nao aceita texto invalido,
rem  ao contrario de set /p, que devolveria uma variavel vazia.
choice /c 12345 /n /m "Escolha (1-5): "

if errorlevel 5 goto todos
if errorlevel 4 goto draw
if errorlevel 3 goto impress
if errorlevel 2 goto calc
if errorlevel 1 goto writer

:writer
call "%~dp0try-it.cmd" --writer
goto fim
:calc
call "%~dp0try-it.cmd" --calc
goto fim
:impress
call "%~dp0try-it.cmd" --impress
goto fim
:draw
call "%~dp0try-it.cmd" --draw
goto fim
:todos
call "%~dp0try-it.cmd" --all
goto fim

:fim
endlocal
