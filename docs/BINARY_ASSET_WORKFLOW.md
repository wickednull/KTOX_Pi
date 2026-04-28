# Binary asset workflow (logos/icons)

If your PR tooling says **"binary files not supported"**, use this workflow:

1. Keep code/markup changes in Git (HTML/CSS/manifest refs).
2. Avoid committing brand-new binary files through text-only patch tools.
3. Reuse an existing tracked image path (for example `web/ktox.png`) and bump a query version (`?v=4`) to refresh caches.
4. If you must replace the actual image bytes, do it with normal `git add` in a full git client (or Git LFS if your hosting policy requires it), then push.

## For iOS/webapp icon refresh

- Delete the old saved web app from Home Screen.
- Re-open the site in Safari.
- Save to Home Screen again.

This forces iOS to re-read manifest/icon metadata instead of reusing stale cached icons.
