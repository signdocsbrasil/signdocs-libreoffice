#!/bin/bash
# ===================================================================
#  SignDocs Brasil - diagnostico (macOS)
#
#  Rode isto se o try-it.command falhar, ou se o login nao completar.
#  Nao instala nada e nao precisa do LibreOffice aberto.
#
#  Gera  signdocs-diagnostico.json  nesta pasta. Mande esse arquivo.
# ===================================================================
set -uo pipefail
cd "$(dirname "$0")"

printf '\n  SignDocs Brasil - diagnostico\n\n'

# Usa o Python do PROPRIO LibreOffice de proposito. No macOS ele traz o
# seu proprio OpenSSL e NAO enxerga o chaveiro do sistema, e e por isso
# que a extensao embarca o cacert.pem da Mozilla. Testar com o Python do
# sistema (ou com o do Homebrew) nao provaria nada sobre esse caminho --
# eles tem trust store proprio e passariam mesmo se a extensao fosse
# quebrar.
PY=""
for candidate in \
    "/Applications/LibreOffice.app/Contents/Resources/python" \
    "$HOME/Applications/LibreOffice.app/Contents/Resources/python" \
    "/Applications/LibreOffice.app/Contents/Frameworks/LibreOfficePython.framework/Versions/Current/bin/python3" \
    "/Applications/LibreOffice.app/Contents/MacOS/python"; do
	if [ -x "$candidate" ]; then PY="$candidate"; break; fi
done

if [ -n "$PY" ]; then
	printf '  Python do LibreOffice: %s\n' "$PY"
else
	printf '  [aviso] Python do LibreOffice nao encontrado - usando o Python\n'
	printf '          do sistema. O resultado do TLS pode nao refletir o que\n'
	printf '          a extensao ve.\n'
	PY="$(command -v python3 || true)"
	if [ -z "$PY" ]; then
		printf '  [ERRO] Nenhum Python disponivel.\n\n'
		read -r -p "  Pressione Enter para fechar." _
		exit 1
	fi
fi

printf '\n'
"$PY" "$(dirname "$0")/diagnostico.py" --stage hml
RC=$?

printf '\n'
if [ "$RC" = "0" ]; then
	printf '  Nenhum problema encontrado nesta maquina.\n'
else
	printf '  Foram encontrados problemas - veja a lista acima.\n'
fi
printf '  Mande o arquivo signdocs-diagnostico.json desta pasta.\n\n'
read -r -p "  Pressione Enter para fechar." _
