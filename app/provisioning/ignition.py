"""Ignition config generator for Fedora CoreOS and Flatcar Linux.

No external tool needed — we generate and serve the Ignition JSON directly.
The machine fetches it during PXE boot via kernel arg:
  ignition.config.url=http://controller:8000/api/v1/provision-files/{machine_id}/config.ign
"""

import json
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)


class IgnitionError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def generate_ignition(
    hostname: str,
    ssh_keys: list[str],
    ip_config: dict | None = None,
    users: list[dict] | None = None,
    systemd_units: list[dict] | None = None,
    files: list[dict] | None = None,
    storage: dict | None = None,
    k8s_join: dict | None = None,
    extra_config: dict | None = None,
) -> dict:
    """Generate an Ignition v3.4 config."""
    config = {
        "ignition": {"version": "3.4.0"},
        "passwd": {"users": []},
        "storage": {"files": []},
        "systemd": {"units": []},
    }

    # Primary user (core)
    core_user = {
        "name": "core",
        "sshAuthorizedKeys": ssh_keys,
        "groups": ["sudo", "docker", "wheel"],
    }
    config["passwd"]["users"].append(core_user)

    # Additional users
    for user in (users or []):
        u = {
            "name": user["name"],
            "sshAuthorizedKeys": user.get("ssh_keys", []),
            "groups": user.get("groups", []),
        }
        if user.get("password_hash"):
            u["passwordHash"] = user["password_hash"]
        config["passwd"]["users"].append(u)

    # Hostname
    config["storage"]["files"].append({
        "path": "/etc/hostname",
        "mode": 0o644,
        "overwrite": True,
        "contents": {"source": f"data:,{hostname}"},
    })

    # Static IP network config (NetworkManager keyfile)
    if ip_config and ip_config.get("ip"):
        nm_config = _build_network_config(ip_config)
        config["storage"]["files"].append({
            "path": "/etc/NetworkManager/system-connections/ens192.nmconnection",
            "mode": 0o600,
            "overwrite": True,
            "contents": {"source": f"data:,{_url_encode(nm_config)}"},
        })

    # K8s join (kubeadm)
    if k8s_join:
        join_script = _build_k8s_join_script(k8s_join)
        config["storage"]["files"].append({
            "path": "/opt/k8s-join.sh",
            "mode": 0o755,
            "overwrite": True,
            "contents": {"source": f"data:,{_url_encode(join_script)}"},
        })
        config["systemd"]["units"].append({
            "name": "k8s-join.service",
            "enabled": True,
            "contents": (
                "[Unit]\n"
                "Description=Join Kubernetes cluster\n"
                "After=network-online.target\n"
                "Wants=network-online.target\n"
                "ConditionPathExists=!/var/lib/k8s-joined\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/opt/k8s-join.sh\n"
                "ExecStartPost=/usr/bin/touch /var/lib/k8s-joined\n"
                "RemainAfterExit=yes\n\n"
                "[Install]\n"
                "WantedBy=multi-user.target\n"
            ),
        })

    # Custom systemd units
    for unit in (systemd_units or []):
        config["systemd"]["units"].append({
            "name": unit["name"],
            "enabled": unit.get("enabled", True),
            "contents": unit["contents"],
        })

    # Custom files
    for f in (files or []):
        config["storage"]["files"].append({
            "path": f["path"],
            "mode": f.get("mode", 0o644),
            "overwrite": True,
            "contents": {"source": f"data:,{_url_encode(f['contents'])}"},
        })

    # Disk/storage config
    if storage:
        if "disks" in storage:
            config["storage"]["disks"] = storage["disks"]
        if "raid" in storage:
            config["storage"]["raid"] = storage["raid"]
        if "filesystems" in storage:
            config["storage"]["filesystems"] = storage["filesystems"]

    # Callback to infra-controller when provisioning is done
    callback_url = f"{settings.callback_base_url}/api/v1/provision-callback"
    config["systemd"]["units"].append({
        "name": "provision-callback.service",
        "enabled": True,
        "contents": (
            "[Unit]\n"
            "Description=Notify infra-controller that provisioning is complete\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "ConditionPathExists=!/var/lib/provision-callback-done\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f'ExecStart=/usr/bin/curl -sf -X POST -H "Content-Type: application/json" '
            f'-d \'{{"hostname": "{hostname}", "status": "complete"}}\' '
            f'"{callback_url}"\n'
            "ExecStartPost=/usr/bin/touch /var/lib/provision-callback-done\n"
            "RemainAfterExit=yes\n"
            "Restart=on-failure\n"
            "RestartSec=30\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        ),
    })

    # Merge extra config
    if extra_config:
        for key in ("passwd", "storage", "systemd"):
            if key in extra_config:
                for sub_key, sub_val in extra_config[key].items():
                    if isinstance(sub_val, list):
                        config[key].setdefault(sub_key, []).extend(sub_val)

    return config


def render_ignition_json(
    hostname: str,
    ssh_keys: list[str],
    ip_config: dict | None = None,
    users: list[dict] | None = None,
    systemd_units: list[dict] | None = None,
    files: list[dict] | None = None,
    storage: dict | None = None,
    k8s_join: dict | None = None,
    extra_config: dict | None = None,
) -> str:
    """Generate and return Ignition config as a JSON string."""
    config = generate_ignition(
        hostname=hostname,
        ssh_keys=ssh_keys,
        ip_config=ip_config,
        users=users,
        systemd_units=systemd_units,
        files=files,
        storage=storage,
        k8s_join=k8s_join,
        extra_config=extra_config,
    )
    return json.dumps(config, indent=2)


def save_ignition_config(machine_id: int, config_json: str) -> str:
    """Save rendered Ignition config to disk for serving."""
    serve_dir = os.path.join(settings.ignition_serve_dir, str(machine_id))
    os.makedirs(serve_dir, exist_ok=True)
    filepath = os.path.join(serve_dir, "config.ign")
    with open(filepath, "w") as f:
        f.write(config_json)
    logger.info(f"Ignition config saved: {filepath}")
    return filepath


def _build_network_config(ip_config: dict) -> str:
    """Build a NetworkManager .nmconnection keyfile."""
    interface = ip_config.get("interface", "ens192")
    ip = ip_config["ip"]
    prefix = ip_config.get("prefix", "24")
    gateway = ip_config.get("gateway", "")
    dns = ip_config.get("dns", [])

    lines = [
        "[connection]",
        f"id={interface}",
        f"interface-name={interface}",
        "type=ethernet",
        "autoconnect=true",
        "",
        "[ipv4]",
        "method=manual",
        f"address1={ip}/{prefix},{gateway}" if gateway else f"address1={ip}/{prefix}",
    ]
    if dns:
        lines.append(f"dns={';'.join(dns)};")
    lines.extend(["", "[ipv6]", "method=disabled"])
    return "\n".join(lines)


def _build_k8s_join_script(k8s_join: dict) -> str:
    """Build a kubeadm join script."""
    api_server = k8s_join["api_server"]
    token = k8s_join["token"]
    ca_hash = k8s_join.get("ca_hash", "")
    extra_args = k8s_join.get("extra_args", "")

    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        "",
        "# Wait for kubelet",
        "until command -v kubeadm &>/dev/null; do sleep 5; done",
        "",
        f"kubeadm join {api_server} \\",
        f"  --token {token} \\",
    ]
    if ca_hash:
        lines.append(f"  --discovery-token-ca-cert-hash sha256:{ca_hash} \\")
    if extra_args:
        lines.append(f"  {extra_args} \\")
    lines[-1] = lines[-1].rstrip(" \\")
    return "\n".join(lines)


def _url_encode(text: str) -> str:
    """URL-encode text for data: URIs in Ignition."""
    import urllib.parse
    return urllib.parse.quote(text, safe="")
