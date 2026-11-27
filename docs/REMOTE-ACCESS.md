# Remote access guidance

HomeMonitor is a LAN-only application. It serves plain HTTP, has no built-in TLS and no
multi-user account system. This page explains safe ways to reach it from outside the home
and the risks of each option.

**There is no hosted relay, no automatic NAT traversal and no "open a port" feature.**
Nothing in this project requires internet access at runtime.

## Threat model in one paragraph

Anyone who can reach TCP 8787 and has the admin token has full control: they can view
devices, approve or revoke them, change settings and delete history. Device tokens are
per-device and cannot call admin routes, but a compromised device can upload false
metrics. Traffic is unencrypted by default, so a passive observer on the path can read
the token and data. Treat the controller as an administrative interface, not a public
website.

## Recommended: VPN

Use a VPN that puts the remote device on the same private network as the controller:

- **WireGuard** on your router, a small server, or a home VPN appliance.
- **Tailscale** or a similar mesh VPN, which handles NAT traversal and device identity.
- Your router's built-in VPN server, if it is maintained and uses modern crypto.

Then open the controller's normal LAN URL, for example `http://192.0.2.10:8787/`, while
connected to the VPN. Keep the controller bound to the LAN interface and do not forward
the port.

Advantages:

- No public listener for HomeMonitor.
- The VPN provides encryption and device authentication.
- The controller's LAN-only assumptions remain true.

Caveats:

- A compromised VPN device can reach the whole LAN, not just HomeMonitor. Use the VPN's
  own access controls where available.
- Split tunneling may route the controller address outside the tunnel. Test the route.
- Mobile VPN clients can be killed by battery managers; reconnect before relying on
  alerts.

## Acceptable with care: TLS reverse proxy

If you need browser access without a VPN, put a reverse proxy in front of HomeMonitor:

```text
Internet --TLS--> reverse proxy (public) --HTTP--> HomeMonitor (loopback)
```

Requirements:

1. **Bind HomeMonitor to loopback only** for this deployment:
   `HOMEMONITOR_HOST=127.0.0.1` or `--host 127.0.0.1`. Agents outside the host then need
   another path (usually the VPN); do not expose the agent API directly.
2. Terminate TLS at the proxy with a valid certificate and modern protocols.
3. Add authentication at the proxy (mTLS, OAuth2 proxy, HTTP basic auth over TLS, or a
   VPN-like access layer). The HomeMonitor admin token is a second factor, not the only
   one.
4. Restrict source addresses/geography where possible and rate-limit `/api/v1/session`
   and `/api/v1/register`.
5. Disable response buffering and compression for `/api/v1/stream` (SSE). Keep keepalives
   flowing.
6. Forward the original `Host` and client address correctly, and do not log query strings
   or authorization headers.
7. Keep the proxy and its TLS stack patched. A proxy is now part of your security
   boundary.

Example nginx fragment (illustrative; adapt names, certificates and access controls):

```nginx
server {
    listen 443 ssl;
    server_name monitor.example.com;

    ssl_certificate     /etc/letsencrypt/live/monitor.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/monitor.example.com/privkey.pem;

    # Add authentication here (mTLS, auth_request, OAuth2 proxy, ...).
    # Do not rely on the HomeMonitor token as the only gate.

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_buffering off;          # required for SSE
        proxy_read_timeout 3600s;
    }
}
```

Test:

- Login works over HTTPS.
- The cookie is accepted (`SameSite=Strict`, no `Secure` flag; the browser sees HTTPS).
- SSE updates arrive without a full refresh.
- `/healthz` is reachable only as intended.
- Login/register rate limits still apply (the controller sees the proxy as one source
  unless you configure real client forwarding; plan for that).
- Removing the proxy's extra authentication does not silently expose the controller.

Do **not**:

- Forward port 8787 directly from the router.
- Put HomeMonitor on a public IP with only the admin token.
- Use a self-signed certificate and click through warnings on a regular basis.
- Share one admin token across many people; there are no roles or audit identities.

## Not recommended: direct port forwarding

Forwarding TCP 8787 to the controller exposes an HTTP admin interface to the internet.
The pairing code and rate limits are not a substitute for TLS and network access control.
If you do this anyway:

- Accept that the token and data can be intercepted.
- Use a very long random admin token and rotate it after any suspected exposure.
- Restrict the source address at the router if your router supports it.
- Monitor logs and revoke unknown devices.
- Migrate to a VPN or TLS proxy as soon as possible.

This project does not support that deployment and will not treat it as a security bug.

## Agents and remote access

Agents make outbound HTTP requests. If the controller is only reachable through a VPN,
install the VPN client on each agent host and keep the controller URL as its VPN/LAN
address. On Android, a VPN app may conflict with battery optimisation; test reconnects
after reboot.

If the controller address changes:

1. Update each agent's `controller_url` or re-run the installer with the new
   `--controller` value.
2. Preserve the controller data directory so existing device tokens remain valid.
3. If the data directory was lost, re-pair every device with a fresh code.
4. Confirm devices return to `online` after the change.

## Admin token handling for remote use

- Use a unique token generated by the server or a long random value.
- Store it in a password manager, not a browser note or chat.
- The dashboard session lasts seven days. Log out on shared browsers.
- Rotating the token: stop the service, set `HOMEMONITOR_ADMIN_TOKEN` (or edit
  `admin_token` in `config.json`), and restart. Existing cookies are checked against the
  new token on their next request.
- Do not put the token in a URL. The SSE endpoint accepts `?token=` for compatibility,
  but proxies and browser history can log it. Prefer the cookie or `Authorization`
  header.

## Device tokens

- Each agent has a random 256-bit token. The controller stores only its SHA-256 hash.
- The plaintext token is in `agent.json` / `android_agent.json`; protect it with OS
  permissions.
- Revoking a device invalidates its hash immediately. Re-pairing creates a new token.
- Do not copy an agent config between devices. Each device should have its own UUID and
  token.

## Backups and remote access

A backup contains the admin token, pairing code, hashed device tokens and monitoring
history. Store backups encrypted and access-controlled. Do not upload a backup to a
public cloud folder or attach it to an issue. If a backup leaks, rotate the admin token,
regenerate the pairing code and revoke devices.

## What is intentionally missing

- Built-in TLS and certificate management.
- User accounts, roles and per-user permissions.
- A cloud relay or remote dashboard service.
- Push notifications to a phone.
- Router/firewall automation.
- Remote device control, shell access or file transfer.

These are scope decisions for a small, self-hosted LAN monitor. Feature requests are
welcome, but they need a threat model that keeps the LAN-only default safe.
