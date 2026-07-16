#!/usr/bin/env python3
"""Infra Controller CLI — manage bare-metal servers from the command line."""

import argparse
import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


def api(method: str, path: str, body: dict | None = None) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        resp = getattr(client, method)(path, json=body)
        if resp.status_code == 204:
            return {"status": "deleted"}
        if resp.status_code >= 400:
            print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)
        return resp.json()


def cmd_list(args):
    machines = api("get", "/api/v1/machines")
    if not machines:
        print("No machines registered.")
        return
    fmt = "{:<5} {:<25} {:<16} {:<15} {:<10} {:<10}"
    print(fmt.format("ID", "Name", "BMC IP", "State", "Power", "Health"))
    print("-" * 85)
    for m in machines:
        print(
            fmt.format(
                m["id"],
                m["name"][:25],
                m["bmc_ip"],
                m["state"],
                m.get("power_state") or "-",
                m.get("health_status") or "-",
            )
        )


def cmd_register(args):
    result = api(
        "post",
        "/api/v1/machines",
        {
            "name": args.name,
            "bmc_ip": args.bmc_ip,
            "bmc_username": args.username,
            "bmc_password": args.password,
            "rack_location": args.rack,
        },
    )
    print(f"Registered machine {result['id']} — enrollment started")


def cmd_info(args):
    result = api("get", f"/api/v1/machines/{args.id}")
    print(json.dumps(result, indent=2, default=str))


def cmd_power(args):
    result = api("post", f"/api/v1/machines/{args.id}/power", {"action": args.action})
    print(f"Power {args.action}: {result.get('status', 'done')}")


def cmd_health(args):
    result = api("get", f"/api/v1/machines/{args.id}/health")
    print(json.dumps(result, indent=2, default=str))


def cmd_discover(args):
    result = api(
        "post",
        "/api/v1/discovery",
        {
            "subnet": args.subnet,
            "bmc_username": args.username,
            "bmc_password": args.password,
        },
    )
    print(f"Discovered {result['discovered']} machines")
    for m in result["machines"]:
        print(f"  {m['bmc_ip']} — {m['name']}")
    for e in result.get("errors", []):
        print(f"  SKIP {e['ip']}: {e['error']}")


def cmd_provision(args):
    params = {}
    if args.os:
        params["os_name"] = args.os
    if args.iso:
        params["iso_url"] = args.iso
    result = api(
        "post",
        f"/api/v1/machines/{args.id}/workflows",
        {"workflow_type": "provision", "params": params},
    )
    print(f"Provision workflow {result['id']} started")


def cmd_decommission(args):
    result = api(
        "post",
        f"/api/v1/machines/{args.id}/workflows",
        {"workflow_type": "decommission"},
    )
    print(f"Decommission workflow {result['id']} started")


def cmd_summary(args):
    result = api("get", "/api/v1/dashboard/summary")
    print(f"Total machines: {result['total_machines']}")
    print(f"By state: {json.dumps(result['by_state'], indent=2)}")
    print(f"By health: {json.dumps(result['by_health'], indent=2)}")
    print(f"By vendor: {json.dumps(result['by_vendor'], indent=2)}")


def main():
    parser = argparse.ArgumentParser(
        prog="icctl", description="Infra Controller CLI"
    )
    parser.add_argument(
        "--url", default=BASE_URL, help="API base URL"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all machines")
    sub.add_parser("summary", help="Fleet summary")

    reg = sub.add_parser("register", help="Register a machine")
    reg.add_argument("--name", required=True)
    reg.add_argument("--bmc-ip", required=True)
    reg.add_argument("--username", required=True)
    reg.add_argument("--password", required=True)
    reg.add_argument("--rack", default=None)

    info = sub.add_parser("info", help="Machine details")
    info.add_argument("id", type=int)

    pwr = sub.add_parser("power", help="Power control")
    pwr.add_argument("id", type=int)
    pwr.add_argument("action", choices=["on", "off", "restart", "force_off", "force_restart"])

    hlth = sub.add_parser("health", help="Health check")
    hlth.add_argument("id", type=int)

    disc = sub.add_parser("discover", help="Discover BMCs on subnet")
    disc.add_argument("--subnet", required=True)
    disc.add_argument("--username", required=True)
    disc.add_argument("--password", required=True)

    prov = sub.add_parser("provision", help="Provision a machine")
    prov.add_argument("id", type=int)
    prov.add_argument("--os", default=None)
    prov.add_argument("--iso", default=None)

    decom = sub.add_parser("decommission", help="Decommission a machine")
    decom.add_argument("id", type=int)

    args = parser.parse_args()
    if args.command:
        globals()[f"cmd_{args.command}"](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
