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

O `client_id` é fixo e vem no pacote — não é credencial, justamente porque
o cliente é público e não tem segredo. Não há registro dinâmico: o Cognito
não implementa a RFC 7591 (ver `pythonpath/signdocs/oauth.py`). Em vez disso,
as oito portas de loopback candidatas estão pré-registradas no app client,
porque o `redirect_uri` é conferido por correspondência exata e não dá para
saber de antemão qual estará livre (`pythonpath/signdocs/config.py`).

A extensão sobe um servidor HTTP efêmero em `127.0.0.1` e abre o navegador
padrão para o consentimento (authorization code + PKCE S256, o fluxo de
aplicativo nativo da RFC 8252). O que ela recebe é um **ID token**, que
identifica a pessoa e sozinho não abre a API: as chamadas vão para o tier
`/libreoffice/*`, que guarda a credencial de API do lado do servidor. O ID
token fica só em memória; o refresh token fica no perfil do LibreOffice, com
permissão restrita.

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

# Fluxo completo contra a API de homologação (precisa de credenciais)
export SIGNDOCS_CLIENT_ID=... SIGNDOCS_CLIENT_SECRET=...
python3 bin/e2e_hml.py

# Testar à mão, sem mexer no seu LibreOffice
bash bin/try-it.sh --hml
```

`bin/try-it.sh` instala a extensão em um perfil descartável
(`-env:UserInstallation`) e abre o Writer. Roda **ao lado** do seu LibreOffice
normal: o seu perfil, as suas extensões e os seus documentos abertos não são
tocados, e não é preciso fechar nada. Para desfazer, apague o diretório do
perfil.

## Release

Marque a tag e o resto é automático:

```bash
git tag -a v0.1.1 -m "..." && git push origin v0.1.1
```

O workflow confere que a tag bate com `description.xml`, roda todos os portões,
constrói a partir da árvore da tag (`git archive`, não da cópia de trabalho) e
publica um rascunho de release com o `.oxt` anexado. A submissão para o
extensions.libreoffice.org continua manual — a listagem é moderada por uma
pessoa na TDF e não existe API.

`bin/e2e_hml.py` roda o fluxo real de ponta a ponta: consentimento pelo
navegador roteirizado, troca do código, rotação do refresh token, exportação de
um PDF pelo próprio LibreOffice, criação de sessão e de envelope, consulta de
status e cancelamento. **Não dispara e-mail**: o envio de um signatário usa
`owner.email` igual ao do signatário (a API entende que remetente e signatário
são a mesma pessoa e não envia convite) e o envelope não usa `owner`. Tudo o
que é criado é cancelado no fim.

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
