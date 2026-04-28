#!/usr/bin/env bash
set -e

echo "[*] Enabling SSH root login on Kali..."

# Make sure OpenSSH server is installed
apt update
apt install -y openssh-server

# Enable root password login
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication yes/' /etc/ssh/sshd_config

# If lines did not exist, add them
grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
grep -q '^KbdInteractiveAuthentication' /etc/ssh/sshd_config || echo 'KbdInteractiveAuthentication yes' >> /etc/ssh/sshd_config

# Set root password
echo "[*] Set root password now:"
passwd root

# Enable and restart SSH
systemctl enable ssh
systemctl restart ssh

echo "[+] Done."
echo "[+] Root SSH login is now enabled."
echo "[+] Connect with: ssh root@YOUR_PI_IP"
