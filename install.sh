#!/usr/bin/env bash
# KTOx_Pi Installer
# Pi Zero 2W · Kali ARM64 · Waveshare 1.44" LCD HAT
# sudo bash install.sh

set -euo pipefail
step()  { printf "\e[1;31m[KTOx]\e[0m %s\n" "$*"; }
info()  { printf "\e[1;32m[ ok ]\e[0m %s\n" "$*"; }
warn()  { printf "\e[1;33m[warn]\e[0m %s\n" "$*"; }
fail()  { printf "\e[1;31m[FAIL]\e[0m %s\n" "$*"; exit 1; }

grep -q $'\r' "$0" && { command -v dos2unix >/dev/null 2>&1 || apt-get install -y dos2unix; dos2unix "$0"; }
[[ $EUID -ne 0 ]] && fail "Run as root: sudo bash install.sh"

FIRMWARE_DIR="$(cd "$(dirname "$0")" && pwd)"
KTOX_DIR="/root/KTOx"

printf "\e[1;31m"
cat << 'BANNER'
 ██╗  ██╗████████╗ ██████╗ ██╗  ██╗       ██████╗ ██╗
 ██║ ██╔╝╚══██╔══╝██╔═══██╗╚██╗██╔╝       ██╔══██╗██║
 █████╔╝    ██║   ██║   ██║ ╚███╔╝        ██████╔╝██║
 ██╔═██╗    ██║   ██║   ██║ ██╔██╗        ██╔═══╝ ██║
 ██║  ██╗   ██║   ╚██████╔╝██╔╝ ██╗       ██║     ██║
 ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝       ╚═╝     ╚═╝
    KTOx_Pi Installer — Pi Zero 2W · wickednull
BANNER
printf "\e[0m\n"

# ── Boot config ───────────────────────────────────────────────────────────────
step "Configuring boot params..."
CFG=/boot/firmware/config.txt; [[ -f $CFG ]] || CFG=/boot/config.txt
info "Config: $CFG"
add_param() { grep -qE "^#?\\s*${1%=*}=" "$CFG" && sed -Ei "s|^#?\\s*${1%=*}=.*|$1|" "$CFG" || echo "$1" >> "$CFG"; }
add_param "dtparam=spi=on"
add_param "dtparam=i2c_arm=on"
add_param "dtparam=i2c1=on"
grep -qE "^dtoverlay=spi0-[12]cs" "$CFG" || echo "dtoverlay=spi0-2cs" >> "$CFG"
if ! grep -q "gpio=6,19,5,26,13,21,20,16=pu" "$CFG"; then
    printf "\n# KTOx Waveshare 1.44 HAT button pull-ups\ngpio=6,19,5,26,13,21,20,16=pu\n" >> "$CFG"
    info "GPIO pull-ups set"
fi

# ── Kernel modules ────────────────────────────────────────────────────────────
step "Loading kernel modules..."
for m in i2c-bcm2835 i2c-dev spi_bcm2835 spidev; do
    grep -qxF "$m" /etc/modules || echo "$m" >> /etc/modules
    modprobe "$m" 2>/dev/null || true
done

# ── APT packages ──────────────────────────────────────────────────────────────
step "Installing packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    python3-scapy python3-netifaces python3-pyudev python3-serial \
    python3-smbus python3-rpi.gpio python3-spidev python3-pil python3-numpy \
    python3-setuptools python3-cryptography python3-requests python3-websockets \
    fonts-dejavu-core \
    nmap ncat tcpdump arp-scan dsniff ettercap-text-only php procps \
    aircrack-ng wireless-tools wpasupplicant iw \
    hashcat john hostapd dnsmasq \
    net-tools ethtool git i2c-tools libglib2.0-dev 2>/dev/null || warn "Some packages failed"

apt-get install -y brcmfmac-nexmon-dkms firmware-nexmon 2>/dev/null \
    || warn "Nexmon unavailable — use external USB adapter for WiFi attacks"

# ── Pip packages ──────────────────────────────────────────────────────────────
step "Installing Python packages..."
pip3 install --break-system-packages rich flask websockets pillow spidev RPi.GPIO requests 2>/dev/null \
    || pip3 install rich flask websockets pillow spidev RPi.GPIO requests
pip3 install --break-system-packages customtkinter 2>/dev/null || true

# ── Font Awesome ──────────────────────────────────────────────────────────────
step "Installing Font Awesome icons..."
FA=/usr/share/fonts/truetype/fontawesome/fa-solid-900.ttf
if [[ ! -f "$FA" ]]; then
    mkdir -p "$(dirname $FA)"
    wget -q "https://use.fontawesome.com/releases/v6.5.1/webfonts/fa-solid-900.ttf" -O "$FA" \
        && info "Font Awesome installed" || warn "FA download failed"
fi

# ── KTOx files ────────────────────────────────────────────────────────────────
step "Installing KTOx to $KTOX_DIR..."
mkdir -p "$KTOX_DIR"
cp "$FIRMWARE_DIR/ktox_pi/ktox_device.py"       "$KTOX_DIR/"
cp "$FIRMWARE_DIR/ktox_pi/LCD_1in44.py"          "$KTOX_DIR/"
cp "$FIRMWARE_DIR/ktox_pi/LCD_Config.py"         "$KTOX_DIR/"
cp "$FIRMWARE_DIR/ktox_pi/rj_input.py"           "$KTOX_DIR/"
cp "$FIRMWARE_DIR/ktox_pi/ktox_lcd.py"           "$KTOX_DIR/" 2>/dev/null || true
cp "$FIRMWARE_DIR/ktox_pi/ktox_payload_runner.py" "$KTOX_DIR/" 2>/dev/null || true
cp "$FIRMWARE_DIR/device_server.py"                    "$KTOX_DIR/"
cp "$FIRMWARE_DIR/web_server.py"                       "$KTOX_DIR/"
cp "$FIRMWARE_DIR/nmap_parser.py"                      "$KTOX_DIR/"
cp "$FIRMWARE_DIR/gui_conf.json"                       "$KTOX_DIR/"
cp "$FIRMWARE_DIR/discord_webhook.txt"                 "$KTOX_DIR/"
cp -r "$FIRMWARE_DIR/web"                              "$KTOX_DIR/"
cp -r "$FIRMWARE_DIR/payloads"                         "$KTOX_DIR/"
[[ -d "$FIRMWARE_DIR/wifi" ]]      && cp -r "$FIRMWARE_DIR/wifi"      "$KTOX_DIR/"
[[ -d "$FIRMWARE_DIR/Responder" ]] && cp -r "$FIRMWARE_DIR/Responder" "$KTOX_DIR/"
[[ -d "$FIRMWARE_DIR/DNSSpoof" ]]  && cp -r "$FIRMWARE_DIR/DNSSpoof"  "$KTOX_DIR/"
mkdir -p "$KTOX_DIR/img"
[[ -f "$FIRMWARE_DIR/img/logo.bmp" ]] && cp "$FIRMWARE_DIR/img/logo.bmp" "$KTOX_DIR/img/"

# Copy KTOx main suite (bundled in same directory as install.sh)
KTOX_SUITE=(
    ktox.py ktox_mitm.py ktox_advanced.py ktox_extended.py
    ktox_defense.py ktox_stealth.py ktox_netattack.py ktox_wifi.py
    ktox_dashboard.py ktox_repl.py ktox_config.py
    scan.py spoof.py requirements.txt
)
for f in "${KTOX_SUITE[@]}"; do
    [[ -f "$FIRMWARE_DIR/$f" ]] && cp "$FIRMWARE_DIR/$f" "$KTOX_DIR/" && info "Copied $f"
done
[[ -d "$FIRMWARE_DIR/assets" ]] && cp -r "$FIRMWARE_DIR/assets" "$KTOX_DIR/"
info "KTOx main suite installed"

# Also install Python dependencies from requirements.txt
[[ -f "$KTOX_DIR/requirements.txt" ]] &&     pip3 install --break-system-packages -r "$KTOX_DIR/requirements.txt" 2>/dev/null || true

chmod +x "$KTOX_DIR/ktox_device.py"
mkdir -p "$KTOX_DIR/loot/MITM" "$KTOX_DIR/loot/Nmap" "$KTOX_DIR/loot/payloads"

# Initialise git repo so auto_update.py can pull from GitHub
step "Configuring git for over-the-air updates..."
if [[ ! -d "$KTOX_DIR/.git" ]]; then
    git -C "$KTOX_DIR" init -q
    git -C "$KTOX_DIR" remote add origin https://github.com/wickednull/KTOx_Pi.git
    git -C "$KTOX_DIR" checkout -b main 2>/dev/null || true
    git -C "$KTOX_DIR" add -A
    git -C "$KTOX_DIR" -c user.email="ktox@device" -c user.name="KTOx_Pi" \
        commit -q -m "KTOx_Pi initial install $(date +%Y-%m-%d)" 2>/dev/null || true
    info "Git repo initialised → github.com/wickednull/KTOx_Pi"
else
    git -C "$KTOX_DIR" remote set-url origin https://github.com/wickednull/KTOx_Pi.git
    info "Git remote updated"
fi

# Symlink /root/KTOx -> /root/KTOx for payload compatibility
[[ ! -e "/root/Raspyjack" ]] && ln -s "$KTOX_DIR" "/root/Raspyjack" && info "Symlinked /root/Raspyjack -> $KTOX_DIR (payload compat)"

# ── WebUI tokens ──────────────────────────────────────────────────────────────
step "Generating WebUI credentials..."
for f in "$KTOX_DIR/.webui_token" "$KTOX_DIR/.webui_session_secret"; do
    [[ ! -s "$f" ]] && python3 -c "import secrets,pathlib; pathlib.Path('$f').write_text(secrets.token_urlsafe(48)+'\\n')" && chmod 600 "$f" && info "Created $f"
done

# ── WiFi pinning ──────────────────────────────────────────────────────────────
step "Pinning WiFi interface names..."
for dev in /sys/class/net/wlan*; do
    [[ -e "$dev" ]] || continue
    DP=$(readlink -f "$dev/device" 2>/dev/null || true)
    if echo "$DP" | grep -q "mmc"; then
        MAC=$(cat "$dev/address" 2>/dev/null || true)
        [[ -n "$MAC" ]] && mkdir -p /etc/systemd/network && cat > /etc/systemd/network/10-ktox-wifi.link << LINK
[Match]
MACAddress=$MAC
[Link]
Name=wlan0
LINK
        info "Pinned onboard WiFi ($MAC) -> wlan0"
    fi
done
systemctl is-active --quiet NetworkManager 2>/dev/null && {
    mkdir -p /etc/NetworkManager/conf.d
    echo -e "[keyfile]\nunmanaged-devices=interface-name:wlan0mon;interface-name:wlan1mon" \
        > /etc/NetworkManager/conf.d/99-ktox.conf
    systemctl restart NetworkManager 2>/dev/null || true
}

# ── Systemd services ──────────────────────────────────────────────────────────
step "Creating systemd services..."

cat > /etc/systemd/system/ktox.service << UNIT
[Unit]
Description=KTOx_Pi LCD Interface
After=network-online.target local-fs.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/ktox_device.py
Restart=on-failure
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$KTOX_DIR
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ktox-device.service << UNIT
[Unit]
Description=KTOx_Pi WebSocket Server :8765
After=network-online.target
[Service]
Type=simple
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/device_server.py
Restart=on-failure
User=root
Environment=PYTHONUNBUFFERED=1
Environment=RJ_WS_TOKEN_FILE=$KTOX_DIR/.webui_token
Environment=RJ_WEB_AUTH_SECRET_FILE=$KTOX_DIR/.webui_session_secret
Environment=RJ_WEB_AUTH_FILE=$KTOX_DIR/.webui_auth.json
Environment=RJ_FRAME_PATH=/dev/shm/ktox_last.jpg
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ktox-webui.service << UNIT
[Unit]
Description=KTOx_Pi WebUI HTTP Server :8080
After=ktox-device.service
Requires=ktox-device.service
[Service]
Type=simple
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/web_server.py
Restart=on-failure
User=root
Environment=PYTHONUNBUFFERED=1
Environment=RJ_WS_TOKEN_FILE=$KTOX_DIR/.webui_token
Environment=RJ_WEB_AUTH_SECRET_FILE=$KTOX_DIR/.webui_session_secret
Environment=RJ_WEB_AUTH_FILE=$KTOX_DIR/.webui_auth.json
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ktox.service ktox-device.service ktox-webui.service
info "3 services enabled"

# ── Auto-login tty1 ───────────────────────────────────────────────────────────
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I \$TERM
EOF
systemctl daemon-reload

# ── Hostname + motd ───────────────────────────────────────────────────────────
hostnamectl set-hostname ktox 2>/dev/null || echo "ktox" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\tktox/" /etc/hosts 2>/dev/null || true

cat > /etc/motd << 'MOTD'
[1;31m
 ██╗  ██╗████████╗ ██████╗ ██╗  ██╗       ██████╗ ██╗
 ██║ ██╔╝╚══██╔══╝██╔═══██╗╚██╗██╔╝       ██╔══██╗██║
 █████╔╝    ██║   ██║   ██║ ╚███╔╝        ██████╔╝██║
 ██╔═██╗    ██║   ██║   ██║ ██╔██╗        ██╔═══╝ ██║
 ██║  ██╗   ██║   ╚██████╔╝██╔╝ ██╗       ██║     ██║
 ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝       ╚═╝     ╚═╝
[0m[1;31m Network Control Suite · Pi Zero 2W · Kali ARM64[0m
[0;31m authorized eyes only · wickednull[0m

[1;37m  WebUI   [0m http://[ip]:8080
[1;37m  WS      [0m ws://[ip]:8765
[1;37m  TUI     [0m python3 /root/KTOx/ktox.py
[1;37m  Status  [0m systemctl status ktox ktox-device ktox-webui
[1;37m  Loot    [0m /root/KTOx/loot/
[1;37m  Payloads[0m /root/KTOx/payloads/ (155 scripts)

MOTD

# ── Health check ──────────────────────────────────────────────────────────────
step "Health checks..."
ls /dev/spidev* 2>/dev/null | grep -q spidev0.0 \
    && info "SPI: $(ls /dev/spidev*)" \
    || warn "SPI not ready — reboot required"

python3 - << 'PY' || warn "Some Python imports failed"
for mod in ("RPi.GPIO","spidev","PIL","numpy","scapy","requests","websockets"):
    try:    __import__(mod.split('.')[0]); print(f"  ok  {mod}")
    except Exception as e: print(f"  FAIL  {mod}: {e}")
PY

echo
printf "\e[1;31m"
echo "╔══════════════════════════════════════════════╗"
echo "║          KTOx_Pi — Install Complete          ║"
echo "╚══════════════════════════════════════════════╝"
printf "\e[0m"
echo
printf "\e[1;37m  Hardware Controls\e[0m"
echo ""
echo "    Joystick UP/DOWN    navigate"
echo "    Joystick CTR/RIGHT  select / enter"
echo "    KEY1                back"
echo "    KEY2                home (any depth)"
echo "    KEY3                stop attack"
echo "    KEY1 + KEY3 (3s)    stealth exit"
echo
printf "\e[1;37m  Access\e[0m"
echo ""
echo "    WebUI   http://[ip]:8080"
echo "    SSH     ssh root@[ip]"
echo "    TUI     python3 /root/KTOx/ktox.py"
echo "    Loot    /root/KTOx/loot/"
echo
printf "\e[1;31m  authorized eyes only · wickednull\e[0m\n"
echo
printf "\e[1;33m  Rebooting in 5s… Ctrl+C to cancel\e[0m\n"
sleep 5 && reboot
