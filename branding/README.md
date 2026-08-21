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
