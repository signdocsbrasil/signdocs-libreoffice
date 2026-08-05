#!/bin/bash
# ===================================================================
#  SignDocs Brasil para LibreOffice - teste em Homologacao (macOS)
#
#  Instala a extensao num perfil descartavel e abre o Writer.
#  Roda AO LADO do seu LibreOffice normal: o seu perfil, as suas
#  extensoes e os seus documentos abertos nao sao tocados, e nao e
#  preciso fechar nada. Para desfazer, apague a pasta do perfil.
#
#  Uso: coloque este arquivo na MESMA PASTA do .oxt e clique duas
#  vezes. Se o macOS recusar, veja o LEIA-ME (quarentena).
#
#  Extensao .command (nao .sh) porque so essa e clicavel no Finder.
# ===================================================================
set -uo pipefail
cd "$(dirname "$0")"

printf '\n  SignDocs Brasil - extensao para LibreOffice\n'
printf '  Ambiente: HOMOLOGACAO (hml)\n\n'

# --- 1. localizar o LibreOffice ------------------------------------
# No macOS tudo vive dentro do bundle .app; nao ha binarios no PATH,
# entao procurar por `which soffice` nao encontra nada.
APP=""
for candidate in \
    "/Applications/LibreOffice.app" \
    "$HOME/Applications/LibreOffice.app" \
    "/Applications/LibreOfficeDev.app"; do
	if [ -x "$candidate/Contents/MacOS/soffice" ]; then APP="$candidate"; break; fi
done
if [ -z "$APP" ]; then
	printf '  [ERRO] LibreOffice nao encontrado em /Applications.\n'
	printf '  Instale em https://pt-br.libreoffice.org/baixe-ja/ e rode de novo.\n\n'
	read -r -p "  Pressione Enter para fechar." _
	exit 1
fi
SOFFICE="$APP/Contents/MacOS/soffice"
UNOPKG="$APP/Contents/MacOS/unopkg"
printf '  LibreOffice: %s\n' "$APP"

# --- 2. localizar o .oxt -------------------------------------------
OXT=""
for f in signdocs-brasil-*.oxt; do
	[ -f "$f" ] && OXT="$PWD/$f" && break
done
if [ -z "$OXT" ]; then
	printf '  [ERRO] Nenhum arquivo signdocs-brasil-*.oxt nesta pasta:\n'
	printf '         %s\n' "$PWD"
	printf '  Coloque o .oxt junto deste script.\n\n'
	read -r -p "  Pressione Enter para fechar." _
	exit 1
fi
printf '  Extensao:    %s\n' "$(basename "$OXT")"

# --- 3. perfil descartavel -----------------------------------------
PROFILE="/tmp/lo-signdocs-try"
if [ "${1:-}" = "--reset" ]; then
	printf '  Apagando perfil anterior...\n'
	rm -rf "$PROFILE"
fi
mkdir -p "$PROFILE/user"

# --- 4. apontar para HOMOLOGACAO antes de abrir ---------------------
# So cria se nao existir: sobrescrever apagaria o refresh token e
# exigiria login a cada execucao.
if [ ! -f "$PROFILE/user/signdocs.json" ]; then
	printf '{"signdocs.stage": "hml"}\n' > "$PROFILE/user/signdocs.json"
	printf '  Ambiente definido como homologacao.\n'
else
	printf '  Perfil ja existe - mantendo a sessao anterior.\n'
	printf '  (use  bash try-it.command --reset  para comecar do zero)\n'
fi

# --- 5. instalar ----------------------------------------------------
printf '\n  Instalando...\n'
if ! "$UNOPKG" add -f -env:UserInstallation="file://$PROFILE" "$OXT"; then
	printf '\n  [ERRO] Falha ao instalar a extensao. Saida acima.\n\n'
	read -r -p "  Pressione Enter para fechar." _
	exit 1
fi
printf '  OK.\n'

# --- 6. abrir -------------------------------------------------------
cat <<'INSTRUCOES'

  Abrindo o Writer.

    Menu:  Ferramentas > Suplementos > SignDocs Brasil

    1. Digite algo no documento - e ele que sera assinado.
    2. Ferramentas > Suplementos > SignDocs Brasil > Enviar para assinatura
    3. Clique em Conectar. O navegador abre em login-hml.signdocs.com.br
    4. Entre com a sua conta de HOMOLOGACAO (nao a de producao)
    5. Volte ao Writer - a janela segue sozinha

INSTRUCOES
printf '    Perfil de teste: %s\n' "$PROFILE"
printf '    (apague essa pasta para desfazer tudo)\n\n'

"$SOFFICE" -env:UserInstallation="file://$PROFILE" --norestore --writer &

printf '  Pronto. Pode fechar esta janela.\n\n'
