#!/bin/bash
# =============================================================================
# reset_usb.sh — Emergency USB bus reset
#
# Force-resets USB bus/device when a camera or serial device freezes.
# Useful when V4L2 devices become unresponsive mid-competition.
#
# Usage:
#   ./scripts/reset_usb.sh              # Reset all USB buses
#   ./scripts/reset_usb.sh /dev/video0  # Reset specific device
#   ./scripts/reset_usb.sh --cameras    # Reset only video devices
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

reset_usb_device() {
    local devpath="$1"
    local usbdev

    # Find the USB device path via sysfs
    usbdev=$(udevadm info -q path -n "$devpath" 2>/dev/null | grep -oP '/usb\d+/\d+-[\d.]+' | head -1)

    if [ -z "$usbdev" ]; then
        warn "Cannot find USB path for $devpath — not a USB device?"
        return 1
    fi

    local auth_file="/sys$usbdev/authorized"
    if [ ! -f "$auth_file" ]; then
        warn "No authorized file at $auth_file"
        return 1
    fi

    echo "Resetting USB device: $devpath (sysfs: $usbdev)"
    echo 0 | sudo tee "$auth_file" > /dev/null
    sleep 1
    echo 1 | sudo tee "$auth_file" > /dev/null
    sleep 2
    ok "Reset complete for $devpath"
}

reset_all_usb_buses() {
    echo "Resetting all USB host controllers..."
    for hci in /sys/bus/pci/drivers/xhci_hcd/*/usb*/authorized; do
        [ -f "$hci" ] || continue
        local bus_path=$(dirname "$hci")
        echo "  Cycling: $bus_path"
        echo 0 | sudo tee "$hci" > /dev/null 2>&1
    done
    sleep 2
    for hci in /sys/bus/pci/drivers/xhci_hcd/*/usb*/authorized; do
        [ -f "$hci" ] || continue
        echo 1 | sudo tee "$hci" > /dev/null 2>&1
    done
    sleep 3

    # Fallback: try via usbreset if available
    if command -v usbreset > /dev/null 2>&1; then
        for dev in /dev/bus/usb/*/*; do
            sudo usbreset "$dev" 2>/dev/null || true
        done
    fi

    ok "All USB buses reset"
}

reset_cameras_only() {
    echo "Resetting camera USB devices..."
    local found=0
    for vid in /dev/video*; do
        [ -c "$vid" ] || continue
        if v4l2-ctl --device="$vid" --info > /dev/null 2>&1; then
            reset_usb_device "$vid" && found=1
        fi
    done
    [ "$found" -eq 0 ] && warn "No camera devices found to reset"
}

# CSI camera reset (unbind/rebind the unicam driver)
reset_csi_camera() {
    echo "Resetting CSI camera interface..."
    local driver_path="/sys/bus/platform/drivers/unicam"
    if [ -d "$driver_path" ]; then
        for dev in "$driver_path"/fe80*; do
            [ -d "$dev" ] || continue
            local devname=$(basename "$dev")
            echo "$devname" | sudo tee "$driver_path/unbind" > /dev/null 2>&1 || true
            sleep 1
            echo "$devname" | sudo tee "$driver_path/bind" > /dev/null 2>&1 || true
            ok "CSI camera driver rebound: $devname"
        done
    else
        # RPi5 uses different driver path
        for mod in bcm2835_unicam rp1_cfe; do
            if lsmod | grep -q "$mod"; then
                sudo rmmod "$mod" 2>/dev/null || true
                sleep 1
                sudo modprobe "$mod" 2>/dev/null || true
                ok "Reloaded kernel module: $mod"
            fi
        done
    fi
    sleep 2
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-}" in
    --cameras)
        reset_cameras_only
        reset_csi_camera
        ;;
    --csi)
        reset_csi_camera
        ;;
    --all|"")
        reset_all_usb_buses
        reset_csi_camera
        ;;
    /dev/*)
        reset_usb_device "$1"
        ;;
    *)
        echo "Usage: $0 [--all|--cameras|--csi|/dev/device]"
        echo ""
        echo "  --all       Reset all USB buses + CSI (default)"
        echo "  --cameras   Reset only video/camera USB devices + CSI"
        echo "  --csi       Reset only CSI camera interface"
        echo "  /dev/xxx    Reset a specific USB device"
        exit 1
        ;;
esac
