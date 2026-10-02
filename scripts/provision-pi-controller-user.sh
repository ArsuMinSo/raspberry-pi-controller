#!/bin/bash
# Create the `pi_controller` SSH user on a kiosk Raspberry Pi, with just enough
# passwordless sudo to run the floor-map provisioning commands (setcap on `iw`,
# restarting the kiosk service) — no broader sudo, no password login.
#
# NOT the same `pi_controller` as scripts/deploy.sh SERVICE_USER (that one runs
# the backend on the Ubuntu controller server) — this is the SSH login account the
# controller uses on each *kiosk* Pi. Same name, two different machines/roles.
#
# Run on the Pi itself (over SSH as an existing sudo-capable user, e.g. `vyroba`),
# once per Pi:
#   PI_CONTROLLER_PUBKEY="ssh-ed25519 AAAA... controller@server" bash scripts/provision-pi-controller-user.sh
#
# Get the controller public key from the server first:
#   cat /home/pi_controller/.ssh/id_rsa.pub
set -euo pipefail

: "${PI_CONTROLLER_PUBKEY:?Set PI_CONTROLLER_PUBKEY to the controller public key (cat /home/pi_controller/.ssh/id_rsa.pub on the server)}"

echo "=== Provisioning pi_controller user ==="

if ! id pi_controller &>/dev/null; then
    sudo useradd -m -s /bin/bash pi_controller
fi
sudo mkdir -p /home/pi_controller/.ssh
sudo chmod 700 /home/pi_controller/.ssh
echo "$PI_CONTROLLER_PUBKEY" | sudo tee /home/pi_controller/.ssh/authorized_keys > /dev/null
sudo chmod 600 /home/pi_controller/.ssh/authorized_keys
sudo chown -R pi_controller:pi_controller /home/pi_controller/.ssh

# Note the escaped comma — sudoers treats a bare comma as a list separator even
# inside the command arguments themselves. Unescaped, it breaks parsing for the
# WHOLE file (not just this line), silently falling back to password-required
# for every rule — that is the actual failure mode if this ever needs re-editing.
sudo tee /etc/sudoers.d/pi_controller > /dev/null <<'EOF'
pi_controller ALL=(ALL) NOPASSWD: /usr/sbin/setcap cap_net_raw\,cap_net_admin+eip /usr/sbin/iw
pi_controller ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart kiosk.service
EOF
sudo chmod 440 /etc/sudoers.d/pi_controller

echo "Validating sudoers syntax (visudo -f needs a TTY, so check instead of edit):"
sudo visudo -c -f /etc/sudoers.d/pi_controller

# The sudoers rule above only permits running setcap — it doesn't apply it. Do that now so a
# plain `iw dev wlan0 scan` (no sudo) works immediately after this script finishes, not just
# after someone remembers to run this by hand.
echo "Applying setcap to iw (so scans work without sudo from here on):"
sudo setcap cap_net_raw,cap_net_admin+eip /usr/sbin/iw
getcap /usr/sbin/iw

echo "=== Done. Set ssh.username: pi_controller in config.yaml on the controller server. ==="
