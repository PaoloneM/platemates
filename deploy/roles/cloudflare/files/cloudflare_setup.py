#!/usr/bin/env python3
"""Configure Cloudflare for PlateMates through its API: idempotent, and convergent (running it
again after a change in the variables applies the change, nothing is configured by hand).

Run by Ansible on the control node (deploy/roles/cloudflare), with its settings in the
environment; prints one JSON object (the tunnel's token among it: Ansible never logs it).

- Zone: SSL Full (strict), HTTPS only, TLS 1.2 at least, WebSockets.
- Access: the admin host behind a login (Google, or a one-time code by email), allowed to the
  app's administrators only. Created before any DNS change, so the admin host is never
  reachable through Cloudflare without it.
- Tunnel `platemates` (cloudflared on the server, outbound only): each host to its Traefik.
- DNS: a host in CF_TUNNEL_HOSTS points to the tunnel, proxied; one that is not keeps (or gets
  back) its direct record: the apex on the server's address, www on the apex, admin on
  127.0.0.1 (the SSH tunnel). Mail records are never touched.
- Rate limit on the public "ask for an invitation" endpoint (the Free plan's one rule).
- Email Routing (incoming mail): on; each address in CF_MAIL_FORWARDS forwarded to its
  destinations (added to the account if new: Cloudflare then asks them to confirm by email);
  rules for other single addresses removed; the catch-all as CF_MAIL_CATCH_ALL says (off:
  dropped). Its own MX and DKIM records are Cloudflare's, never touched here.
- Mail records (CF_MAIL_RECORDS: SPF, DMARC, the sending service's DKIM and verification):
  each kept as given. A TXT starting with "v=spf1" or "v=DMARC1" replaces the one of its kind
  at that name (a domain may have only one); other records are added beside what is there.

Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
TOKEN = os.environ["CF_API_TOKEN"]
ACCOUNT = os.environ["CF_ACCOUNT_ID"]
ZONE_NAME = os.environ["CF_ZONE"]
ADMIN_HOST = os.environ["CF_ADMIN_HOST"]
ORIGIN_IP = os.environ["CF_ORIGIN_IP"]
TUNNEL_HOSTS = [h for h in os.environ.get("CF_TUNNEL_HOSTS", "").split(",") if h]
ACCESS_EMAILS = [e.strip() for e in os.environ.get("CF_ACCESS_EMAILS", "").split(",") if e.strip()]
GOOGLE_ID = os.environ.get("CF_GOOGLE_CLIENT_ID", "")
GOOGLE_SECRET = os.environ.get("CF_GOOGLE_CLIENT_SECRET", "")
MAIL_RECORDS = json.loads(os.environ.get("CF_MAIL_RECORDS") or "[]")
# [{"from": "chef@…", "to": "a@…,b@…"}]: destinations as one comma-separated text.
MAIL_FORWARDS = [
    {"from": f["from"], "to": [t.strip() for t in str(f["to"]).split(",") if t.strip()]}
    for f in json.loads(os.environ.get("CF_MAIL_FORWARDS") or "[]")
]
MAIL_CATCH_ALL = os.environ.get("CF_MAIL_CATCH_ALL", "")
TUNNEL_NAME = "platemates"
ACCESS_APP_NAME = "PlateMates admin"
WWW = f"www.{ZONE_NAME}"
# Where each host goes from cloudflared, inside the compose network (TLS to Traefik, checked
# against the host's own certificate).
ORIGINS = {ZONE_NAME: "https://traefik:443", WWW: "https://traefik:443", ADMIN_HOST: "https://traefik-admin:443"}
# A host's record when it does not go through the tunnel.
DIRECT = {ZONE_NAME: ("A", ORIGIN_IP), WWW: ("CNAME", ZONE_NAME), ADMIN_HOST: ("A", "127.0.0.1")}

changes: list[str] = []


def call(method: str, path: str, body: dict | list | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}")
        if method == "GET" and exc.code == 404:
            return payload
        sys.exit(f"{method} {path}: HTTP {exc.code} {payload.get('errors')}")


def result(method: str, path: str, body=None):
    return call(method, path, body).get("result")


def zone_settings(zone: str) -> None:
    wanted = {"ssl": "strict", "always_use_https": "on", "min_tls_version": "1.2", "websockets": "on"}
    for key, value in wanted.items():
        if result("GET", f"/zones/{zone}/settings/{key}")["value"] != value:
            result("PATCH", f"/zones/{zone}/settings/{key}", {"value": value})
            changes.append(f"zone {key} = {value}")


def organization() -> None:
    """The name Access's login page shows (the team's default is a random one)."""
    org = result("GET", f"/accounts/{ACCOUNT}/access/organizations")
    if org.get("name") != "PlateMates":
        result("PUT", f"/accounts/{ACCOUNT}/access/organizations",
               {"name": "PlateMates", "auth_domain": org["auth_domain"]})
        changes.append("access: organization named PlateMates")


def identity_providers() -> list[str]:
    existing = result("GET", f"/accounts/{ACCOUNT}/access/identity_providers") or []
    by_type = {p["type"]: p for p in existing}
    ids = []
    if "onetimepin" not in by_type:
        by_type["onetimepin"] = result("POST", f"/accounts/{ACCOUNT}/access/identity_providers",
                                       {"name": "Codice via email", "type": "onetimepin", "config": {}})
        changes.append("access: one-time code by email")
    ids.append(by_type["onetimepin"]["id"])
    if GOOGLE_ID and GOOGLE_SECRET:
        body = {"name": "Google", "type": "google",
                "config": {"client_id": GOOGLE_ID, "client_secret": GOOGLE_SECRET}}
        if "google" in by_type:
            # The secret cannot be read back: written on every run (convergent).
            result("PUT", f"/accounts/{ACCOUNT}/access/identity_providers/{by_type['google']['id']}", body)
        else:
            by_type["google"] = result("POST", f"/accounts/{ACCOUNT}/access/identity_providers", body)
            changes.append("access: Google")
        ids.append(by_type["google"]["id"])
    return ids


def access_app(idps: list[str]) -> str:
    if not ACCESS_EMAILS:
        sys.exit("No administrator email for Access (CF_ACCESS_EMAILS).")
    apps = result("GET", f"/accounts/{ACCOUNT}/access/apps") or []
    app = next((a for a in apps if a.get("domain") == ADMIN_HOST), None)
    body = {
        "name": ACCESS_APP_NAME, "type": "self_hosted", "domain": ADMIN_HOST,
        "session_duration": "24h", "allowed_idps": idps, "auto_redirect_to_identity": False,
        "app_launcher_visible": False,
    }
    if app is None:
        app = result("POST", f"/accounts/{ACCOUNT}/access/apps", body)
        changes.append(f"access: application for {ADMIN_HOST}")
    else:
        app = result("PUT", f"/accounts/{ACCOUNT}/access/apps/{app['id']}", body)
    policy = {
        "name": "PlateMates administrators", "decision": "allow", "precedence": 1,
        "include": [{"email": {"email": e}} for e in ACCESS_EMAILS],
    }
    policies = result("GET", f"/accounts/{ACCOUNT}/access/apps/{app['id']}/policies") or []
    current = next((p for p in policies if p["name"] == policy["name"]), None)
    if current is None:
        result("POST", f"/accounts/{ACCOUNT}/access/apps/{app['id']}/policies", policy)
        changes.append("access: administrators policy")
    else:
        result("PUT", f"/accounts/{ACCOUNT}/access/apps/{app['id']}/policies/{current['id']}", policy)
    return app["aud"]


def tunnel() -> tuple[str, str]:
    found = result("GET", f"/accounts/{ACCOUNT}/cfd_tunnel?name={TUNNEL_NAME}&is_deleted=false") or []
    if found:
        tunnel_id = found[0]["id"]
    else:
        tunnel_id = result("POST", f"/accounts/{ACCOUNT}/cfd_tunnel",
                           {"name": TUNNEL_NAME, "config_src": "cloudflare"})["id"]
        changes.append("tunnel created")
    ingress = [
        {"hostname": host, "service": service, "originRequest": {"originServerName": host}}
        for host, service in ORIGINS.items()
    ] + [{"service": "http_status:404"}]
    config = result("GET", f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/configurations") or {}
    if (config.get("config") or {}).get("ingress") != ingress:
        result("PUT", f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/configurations",
               {"config": {"ingress": ingress}})
        changes.append("tunnel routes")
    token = result("GET", f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/token")
    return tunnel_id, token


def dns(zone: str, tunnel_id: str) -> None:
    records = result("GET", f"/zones/{zone}/dns_records?per_page=200") or []
    for host in ORIGINS:
        if host in TUNNEL_HOSTS:
            kind, content, proxied = "CNAME", f"{tunnel_id}.cfargotunnel.com", True
        else:
            (kind, content), proxied = DIRECT[host], False
        mine = [r for r in records if r["name"] == host and r["type"] in ("A", "AAAA", "CNAME")]
        if any(r["type"] == kind and r["content"] == content and r["proxied"] == proxied for r in mine) and len(mine) == 1:
            continue
        for record in mine:
            result("DELETE", f"/zones/{zone}/dns_records/{record['id']}")
        result("POST", f"/zones/{zone}/dns_records",
               {"type": kind, "name": host, "content": content, "proxied": proxied, "ttl": 1})
        changes.append(f"dns {host}: {kind} {content}{' (proxied)' if proxied else ''}")


def mail_records(zone: str) -> None:
    for wanted in MAIL_RECORDS:
        kind, name, content = wanted["type"], wanted["name"], wanted["content"]
        same = result("GET", f"/zones/{zone}/dns_records?type={kind}&name={name}") or []
        # TXT content comes back quoted.
        def text(record):
            return record["content"].strip('"')
        if any(text(r) == content for r in same):
            continue
        unique = next((p for p in ("v=spf1", "v=DMARC1") if content.startswith(p)), None)
        for record in same:
            if kind != "TXT" or (unique and text(record).startswith(unique)):
                result("DELETE", f"/zones/{zone}/dns_records/{record['id']}")
        result("POST", f"/zones/{zone}/dns_records",
               {"type": kind, "name": name, "content": content, "ttl": 1, "proxied": False})
        changes.append(f"dns {name}: {kind} {content[:40]}")


def email_routing(zone: str) -> None:
    if not result("GET", f"/zones/{zone}/email/routing").get("enabled"):
        result("POST", f"/zones/{zone}/email/routing/enable", {})
        changes.append("email routing on")
    known = {a["email"].lower() for a in result("GET", f"/accounts/{ACCOUNT}/email/routing/addresses") or []}
    for target in sorted({t.lower() for f in MAIL_FORWARDS for t in f["to"]} - known):
        result("POST", f"/accounts/{ACCOUNT}/email/routing/addresses", {"email": target})
        changes.append("email routing: new destination (to confirm by email)")
    rules = result("GET", f"/zones/{zone}/email/routing/rules") or []
    by_address = {
        m["value"].lower(): r for r in rules for m in r["matchers"] if m["type"] == "literal"
    }
    wanted = {f["from"].lower(): sorted(t.lower() for t in f["to"]) for f in MAIL_FORWARDS}
    for address, targets in wanted.items():
        body = {
            "name": f"PlateMates: {address}", "enabled": True,
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "forward", "value": targets}],
        }
        rule = by_address.get(address)
        current = rule and rule["enabled"] and sorted(
            v.lower() for a in rule["actions"] if a["type"] == "forward" for v in a["value"]
        ) == targets
        if current:
            continue
        if rule:
            result("PUT", f"/zones/{zone}/email/routing/rules/{rule['tag']}", body)
        else:
            result("POST", f"/zones/{zone}/email/routing/rules", body)
        changes.append(f"email routing: {address} forwarded")
    for address, rule in by_address.items():
        if address not in wanted:
            result("DELETE", f"/zones/{zone}/email/routing/rules/{rule['tag']}")
            changes.append(f"email routing: rule for {address} removed")
    catch_all = result("GET", f"/zones/{zone}/email/routing/rules/catch_all")
    targets = sorted(t.strip().lower() for t in MAIL_CATCH_ALL.split(",") if t.strip())
    action = {"type": "forward", "value": targets} if targets else {"type": "drop", "value": []}
    current_actions = [{"type": a["type"], "value": sorted(a.get("value") or [])} for a in catch_all["actions"]]
    if catch_all["enabled"] != bool(targets) or (targets and current_actions != [action]):
        result("PUT", f"/zones/{zone}/email/routing/rules/catch_all", {
            "enabled": bool(targets), "matchers": [{"type": "all"}], "actions": [action]})
        changes.append(f"email routing: catch-all {'to ' + str(len(targets)) + ' address(es)' if targets else 'off'}")


def rate_limit(zone: str) -> None:
    """No rate-limiting rules: the one public form they guarded (asking for an invitation
    anonymously) is gone; requests now need an account and are limited by the app."""
    current = call("GET", f"/zones/{zone}/rulesets/phases/http_ratelimit/entrypoint").get("result") or {}
    if current.get("rules"):
        result("PUT", f"/zones/{zone}/rulesets/phases/http_ratelimit/entrypoint", {"rules": []})
        changes.append("rate limits removed")


def main() -> None:
    zones = result("GET", f"/zones?name={ZONE_NAME}") or []
    if not zones or zones[0]["status"] != "active":
        sys.exit(f"Zone {ZONE_NAME} is not active on Cloudflare yet (nameservers).")
    zone = zones[0]["id"]
    zone_settings(zone)
    organization()
    aud = access_app(identity_providers())  # before any DNS change
    tunnel_id, token = tunnel()
    dns(zone, tunnel_id)
    email_routing(zone)
    mail_records(zone)
    rate_limit(zone)
    print(json.dumps({"changed": bool(changes), "changes": changes, "tunnel_id": tunnel_id,
                      "tunnel_token": token, "access_aud": aud}))


if __name__ == "__main__":
    main()
