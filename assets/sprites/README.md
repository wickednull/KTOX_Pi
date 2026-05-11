# Local Loki Sprite Assets

Put the artist-provided Loki sprite PNGs in this directory when generating or
installing Loki themes. PNG files are intentionally ignored by git because the
review system does not support binary diffs.

Expected layout:

```text
assets/sprites/IDLE.png
assets/sprites/IDLE1.png
assets/sprites/IDLE2.png
assets/sprites/IDLE3.png
assets/sprites/IDLE4.png
assets/sprites/<Action>.png
assets/sprites/<Action>1.png ... <Action>4.png
assets/sprites/Background/main_bg.png
assets/sprites/Background/main_bg_portrait.png
assets/sprites/Background/menu_bg.png
assets/sprites/Background/settings_bg.png
assets/sprites/Background/pause_bg.png
assets/sprites/Background/pause_bg_portrait.png
```

The generator copies correctly sized files byte-for-byte into the generated
Loki theme folders and fails if a required local sprite asset is missing.
