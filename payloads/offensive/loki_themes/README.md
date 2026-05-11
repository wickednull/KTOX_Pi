# KTOx Loki Cyberpunk Theme Pack

This source-only pack defines four skin-based Loki themes. PNG assets are
generated locally from the payload-local `payloads/offensive/loki_theme_generator.py`
module (also exposed through `tools/generate_loki_cyberpunk_themes.py`) and
copied into a `brainphreak/loki-recon` checkout under `loki/themes/`.

| Theme ID | Theme Name | Mood |
| --- | --- | --- |
| `neon_runner` | Neon Runner | Hot pink and cyan street-ops cyberpunk |
| `chrome_mantis` | Chrome Mantis | Acid green black-chrome intrusion deck |
| `edge_fury` | Edge Fury | Gold/redline edge-runner crew vibe |
| `icewire_ghost` | Icewire Ghost | White-blue ICE and stealth netrunning |

Each generated theme contains:

- Full-resolution landscape and portrait main skins.
- Menu, settings, and pause backgrounds.
- Sequential pixel-runner animation frames for every supported Loki action.
- Status icons for every supported Loki action.
- Cyberpunk commentary text grouped by action.
- Web UI palette colors and custom mood preset labels.

## Install

After `setup_loki.sh` has cloned Loki, install or refresh the pack with:

```bash
python3 payloads/offensive/install_loki_themes.py /root/KTOx
```

For a development checkout, run:

```bash
python3 payloads/offensive/install_loki_themes.py .
```

`setup_loki.sh` also runs this installer automatically after Loki has been
cloned and its Python environment is ready, so fresh installs get the themes
without committing binary PNG files to this repository.

## Regenerate Art

The images are generated deterministically and intentionally not tracked in git. To create a local preview copy under this folder, run:

```bash
python3 tools/generate_loki_cyberpunk_themes.py
# or, on payload-only installs that do not include tools/:
python3 payloads/offensive/loki_theme_generator.py
```

Run that command after changing palettes, layouts, or sprite drawing logic.
