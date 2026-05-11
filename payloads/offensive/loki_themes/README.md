# KTOx Loki Cyberpunk Theme Pack

This source-only pack defines four skin-based Loki themes. Generated Loki theme
PNGs stay out of git, and the artist-provided source PNGs under
`assets/sprites/` are local/ignored assets because binary diffs are unsupported.
The generator copies those local sprites/backgrounds into a
`brainphreak/loki-recon` checkout under `loki/themes/`.

| Theme ID | Theme Name | Mood |
| --- | --- | --- |
| `neon_runner` | Neon Runner | Hot pink and cyan street-ops cyberpunk |
| `chrome_mantis` | Chrome Mantis | Acid green black-chrome intrusion deck |
| `edge_fury` | Edgerunners | Gold/redline Night City crew vibe |
| `icewire_ghost` | Icewire Ghost | White-blue ICE and stealth netrunning |

Each generated theme contains:

- Full-resolution landscape and portrait main skins.
- Menu, settings, and pause backgrounds.
- Sequential animation frames cropped and scaled from sprite-sheet source art.
- Status icons for every supported Loki action.
- Cyberpunk commentary text grouped by action.
- Web UI palette colors and custom mood preset labels.

## Sprite Sources

The generator uses the real artist-provided per-action PNGs in `assets/sprites/` exactly as the source of truth. The 46x46 files (`IDLE.png`, `SSHBruteforce.png`, and so on) become Loki status icons, and the 175x175 files (`IDLE1.png` through `IDLE4.png`, etc.) become the animation frames. The generator does not redraw, recolor, remove backgrounds from, or add props over the uploaded sprites.

`assets/sprites/Background/` (or `assets/sprites/Backgrounds/`) is used for the Loki main, menu, settings, and pause backgrounds when matching filenames are present.

The Loki-only actions that do not have uploaded art are mapped to existing real sprites instead of synthetic characters:

| Loki action | Uploaded sprite reused |
| --- | --- |
| `LogStandalone` | `IDLE` |
| `LogStandalone2` | `NetworkScanner` |
| `ZombifySSH` | `SSHBruteforce` |
| `NucleiScanner` | `NmapVulnScanner` |
| `SearchSploitEnricher` | `NmapVulnScanner` |
| `TestSSLScanner` | `NmapVulnScanner` |

Normal builds require these uploaded PNGs and fail loudly if an action asset is missing, so the installer never silently substitutes generated fake sprites.

## Install

After `setup_loki.sh` has cloned Loki, install or refresh the pack with:

```bash
python3 payloads/offensive/install_loki_themes.py /root/KTOx --activate neon_runner
```

For a development checkout, run:

```bash
python3 payloads/offensive/install_loki_themes.py . --activate neon_runner
```

`setup_loki.sh` also runs this installer automatically after Loki has been
cloned and its Python environment is ready, so fresh installs get the themes
without committing binary PNG files to this repository.

## Regenerate Art

The Loki-ready theme folders are assembled deterministically from the source PNG assets and intentionally keep generated `images/` output out of git. To create a local preview copy under this folder, run:

```bash
python3 tools/generate_loki_cyberpunk_themes.py
# or, on payload-only installs that do not include tools/:
python3 payloads/offensive/loki_theme_generator.py
```

Run that command after changing palettes, layouts, commentary, or source assets.
