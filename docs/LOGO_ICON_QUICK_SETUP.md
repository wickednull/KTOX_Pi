# Quick setup: change KTOx logo/icon (simple)

If you just want your new image to appear in the WebUI and iOS web app icon, do this:

## 1) Replace one file

- Put your desired image at:
  - `assets/logo.png`

Use the same filename so you don't have to edit code.

## 2) Bump cache version once

Open these files and change `?v=5` to `?v=6` (or any new number):

- `web/index.html`
- `web/ide.html`
- `web/manifest.webmanifest`

This forces browsers/iOS to refresh old cached icons.

## 3) Save and restart web service

```bash
sudo systemctl restart ktox-web || true
```

(If your service name is different, restart that one instead.)

## 4) Re-add Home Screen app on iPhone

1. Delete old saved web app icon.
2. Open Safari to KTOx WebUI again.
3. Share → Add to Home Screen.

Done.
