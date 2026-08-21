# Screenshots for the extensions.libreoffice.org listing

Upload in this order. The site shows the first one as the card image, and most
visitors never scroll past the third, so the two differentiators — multi-signer
sending and ICP-Brasil — are first and second on purpose.

| # | File | What it shows |
|---|---|---|
| 1 | `1-enviar-para-assinatura.png` | The send dialog over the open contract: two signers, signature type, order. The hero — it establishes "this is LibreOffice" and "this sends for signature" in one frame. |
| 2 | `2-certificado-icp-brasil.png` | Same dialog with *Certificado digital ICP-Brasil* selected, the order control disabled, and the reason spelled out: "Certificado exige ordem sequencial." Credibility plus a real product rule in one shot. |
| 3 | `3-conferir-envio.png` | The confirmation step, listing what is about to be sent and to whom, before anything leaves. |
| 4 | `4-conferir-o-documento.png` | The PDF preview at "Página 1 de 3", with the contract legible. Answers the question the feature exists for: exactly what leaves this machine. |
| 5 | `5-enviado.png` | Result. No links on screen — each signer's link went to their own mailbox, and signer 2 is marked "convite após o signatário 1 assinar", so staged sequential delivery is visible. |
| 6 | `6-acompanhar.png` | Tracking from inside LibreOffice: both signers, CPF, status, 0/2. |

## What was edited, and why

The "Remetente" line in 1, 2 and 3 originally showed the signed-in account's
real address. A listing image is public, permanent and scraped, so it was
replaced with `demo@signdocs.com.br`, rendered in Cantarell 21px on the dialog's
own background (#f6f5f4) at text colour #2e3436 — the same font the GNOME
toolkit drew the original with, so the substitution is not visible.

Nothing else in the frames is edited. Every identifier shown belongs to
`contrato-modelo.odt`: the two canonical Brazilian example CPFs and
`@example.com` addresses, which IANA reserves permanently.

Metadata is stripped from all six.

## If these are ever re-shot

Keep the sender neutral at capture time rather than editing afterwards, and
keep the raw files out of git — `branding/.gitignore` covers the default
GNOME capture names.
