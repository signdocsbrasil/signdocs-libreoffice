# Listing assets

Not shipped inside the `.oxt` — these are for the extensions.libreoffice.org
listing and anywhere else the project needs a mark at display size.

## `project-logo.png` — 256x256, transparent

Derived from `external-api/hosted-dropbox-app/src/signdocs-logo.png`, which is
the same mark painted on an opaque dark-slate background. That background is
fine inside an app chrome and wrong on a listing page, where it renders as a
dark tile against whatever the site's own background happens to be, in either
theme.

The circle sits at exactly `345x345+84+84` in the 512x512 original, so it is
masked to that circle rather than flood-filled — the original's background is a
gradient, and a fuzz tolerance wide enough to swallow it also eats the mark's
own outer ring:

```sh
magick -size 512x512 xc:black -fill white -draw "circle 256,256 256,86" \
  -alpha off mask.png
magick signdocs-logo.png mask.png -alpha off -compose CopyOpacity -composite \
  -trim +repage -resize 256x256 -strip project-logo.png
```

256 rather than 512: the circle is 345px at its native size, so anything above
that is invented detail at four times the weight.

## `contrato-modelo.odt` — the document used in listing screenshots

A fictitious service contract, three pages, with a signature block on the last
one. Three pages because the preview screenshot has to show paging working; a
one-page document makes the page controls look decorative.

Every identifier in it is a checksum-valid test value already published in this
repo's own tests, so the signer form accepts them and none of them identifies a
real person or company:

| | |
|---|---|
| CNPJ | `11.222.333/0001-81`, `11.444.777/0001-61` |
| CPF | `529.982.247-25`, `123.456.789-09` |

It carries a "MODELO — DOCUMENTO FICTÍCIO PARA DEMONSTRAÇÃO" line at the top.
Delete it if it crowds the shot, but it is cheap insurance against a screenshot
being read as a real client engagement.

Clause 10 cites MP 2.200-2/2001 and Lei 14.063/2020 on purpose: it puts the
legal basis for the signature inside the document being signed, so the
screenshot explains itself without a caption.
