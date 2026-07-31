# SignDocs Brasil para LibreOffice

Envie o documento aberto para assinatura eletrônica com validade jurídica no
Brasil (MP 2.200-2/2001 e Lei 14.063/2020), sem sair do LibreOffice.

Funciona no Writer, Calc, Impress e Draw, no Linux, Windows e macOS.

> **Estado: 0.1.0 — esqueleto.** A cadeia de registro (menu, barra de
> ferramentas, protocolo, componente Python) está completa e validada em um
> LibreOffice real. Os comandos ainda são espaços reservados.

---

## Como vai funcionar

1. Você preenche remetente, tipo de assinatura e signatários.
2. Uma tela de conferência mostra documento, tipo, ordem e cada signatário com
   CPF/CNPJ formatado. Nada foi enviado ainda.
3. Ao confirmar, a extensão exporta o documento aberto para PDF **localmente**
   (`storeToURL` com o filtro PDF do módulo) e envia inline para a API.
4. 1 signatário → `POST /v1/signing-sessions`.
   2+ signatários → `POST /v1/envelopes` + `POST /v1/envelopes/{id}/sessions`.
5. Os links por signatário são montados como `{url}?cs={clientSecret}`.
6. Concluída a assinatura, o PDF assinado volta para o lado do documento
   original como `<nome>-assinado.pdf`.

Nada sai da sua máquina antes de você confirmar o envio.

## Instalação

```bash
# usuário atual
unopkg add -f signdocs-brasil-<versão>.oxt

# toda a máquina — nenhum processo do LibreOffice pode estar rodando
unopkg add --shared --suppress-license signdocs-brasil-<versão>.oxt

# conferir depois
unopkg validate br.com.signdocs.libreoffice
```

O modo `--shared` é o caminho para implantação em parque de máquinas: um único
arquivo distribuído por GPO, Ansible ou script de imagem atende todos os
usuários da estação.

## Autenticação

A extensão é um **cliente público OAuth 2.1** — não embarca segredo nenhum.

Na primeira conexão ela se registra sozinha no servidor de autorização
(RFC 7591 Dynamic Client Registration), sobe um servidor HTTP efêmero em
`127.0.0.1` e abre o navegador padrão para o consentimento
(authorization code + PKCE S256, o fluxo de aplicativo nativo da RFC 8252).
O token de acesso fica só em memória; o refresh token fica no perfil do
LibreOffice, com permissão restrita.

## Autoteste

Instalações corporativas costumam falhar antes de qualquer diálogo aparecer —
perfil somente leitura, PyUNO ausente, TLS sem CA. O comando de autoteste
grava um relatório JSON no perfil do usuário em vez de abrir uma janela:

```
br.com.signdocs.libreoffice:SelfTest   →   $(user)/signdocs-selftest.json
```

Peça esse arquivo ao cliente antes de investigar qualquer outra coisa.

## Desenvolvimento

```bash
bash bin/lint.sh          # ruff + XML + nome de implementação + imports UNO
python3 -m pytest tests/  # lógica pura, sem office
bash bin/build-oxt.sh     # → signdocs-brasil-<versão>.oxt
bash bin/check-oxt.sh     # forma do pacote + unopkg add/list/validate real
bash bin/smoke-oxt.sh     # office headless: menu registrado + dispatch executa
```

Nenhuma dependência Python de terceiros, nunca: o LibreOffice traz o próprio
interpretador, sem `pip`. `bin/check-oxt.sh` recusa o pacote se qualquer módulo
importar algo fora da biblioteca padrão, e `bin/lint.sh` recusa `import uno` em
escopo de módulo fora de `ui/` — é isso que mantém a lógica testável sem um
office rodando.

`bin/check-oxt.sh` e `bin/smoke-oxt.sh` instalam em um perfil descartável
(`-env:UserInstallation`), então nunca tocam no seu LibreOffice nem exigem que
ele esteja fechado.

### Por que os testes de integração não são opcionais

Os dois modos de falha que importam aqui **não geram erro nenhum**: a extensão
instala normalmente e simplesmente não faz nada.

- Um `media-type` errado em `META-INF/manifest.xml` faz o componente ser
  ignorado em silêncio.
- Se o nome de implementação em `ProtocolHandler.xcu` divergir do registrado
  por `g_ImplementationHelper`, o menu aparece e todo clique é um no-op.

Nenhum dos dois é visível em teste unitário nem no log do office. Por isso
`bin/smoke-oxt.sh` sobe um LibreOffice de verdade e verifica os dois
diretamente. Os repositórios irmãos (Nextcloud e ONLYOFFICE) já entregaram
exatamente essa classe de defeito.

## Relação com os outros canais

Irmão de `signdocs-nextcloud` e `signdocs-onlyoffice`: mesma API, mesma
ramificação sessão/envelope, hospedeiro diferente. Os validadores de CPF/CNPJ
são um port direto do `CpfCnpjValidator` do app Nextcloud, para que os três
canais recusem exatamente as mesmas entradas.

## Licença

MPL-2.0 (veja `LICENSE`). Marcas não estão incluídas na licença — veja
`TRADEMARK.md`.

Esta extensão não é um produto da The Document Foundation e não é endossada
por ela.
