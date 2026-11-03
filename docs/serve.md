# Run as a service

Prompt Vault v1 has **no authentication**: a service should stay on the loopback interface and be reachable only over SSH, a VPN, or a reverse proxy with auth and TLS. These are documentation-only examples (no unit files are shipped or packaged); adapt the paths and user to your system.

## Linux with systemd

Create a dedicated user (no login) and a data directory it owns:

```bash
sudo useradd --system --home /var/lib/promptvault --shell /usr/sbin/nologin promptvault
sudo mkdir -p /var/lib/promptvault && sudo chown promptvault:promptvault /var/lib/promptvault
```

Install the package for that user, e.g. with pipx run as the service user (`sudo -u promptvault pipx install 'prompt-vault[xlsx]'`), or use a plain virtualenv under `/opt/promptvault`.

`/etc/systemd/system/promptvault.service`:

```ini
[Unit]
Description=Prompt Vault (self-hosted prompt library)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=promptvault
Group=promptvault
Environment=PV_DATA_DIR=/var/lib/promptvault
Environment=PV_HOST=localhost
Environment=PV_PORT=8080
ExecStart=/home/promptvault/.local/bin/promptvault serve
Restart=on-failure
RestartSec=5

# Hardening: the app only needs to read its code and write its data directory
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/promptvault
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictSUIDSGID=true
MemoryDenyWriteExecute=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now promptvault
curl http://localhost:8080/api/v1/health    # verify
```

If you installed with pipx, check the real path with `sudo -u promptvault which promptvault` and put it in `ExecStart`. `ProtectSystem=strict` makes the whole filesystem read-only, so `ReadWritePaths` must cover the data directory; the seed library is loaded from inside the package, so nothing else is written.

## Windows with Task Scheduler

1. Install the package (`pipx install 'prompt-vault[xlsx]'` or a venv) and note the full path to `promptvault.exe` (`where promptvault`).
2. Open **Task Scheduler** → *Create Task*: run **whether user is logged on or not**, trigger *at startup* (delay 30 s), action: program `promptvault.exe`, arguments `serve --host localhost --port 8080`.
3. Set the data directory in the task's environment or the user's environment (`PV_DATA_DIR`), or let it default to `%USERPROFILE%\.promptvault`.
4. *Start in* should be a writable directory; uncheck "Stop the task if it runs longer than".
5. Verify after a restart: `Invoke-WebRequest http://localhost:8080/api/v1/health`.

The same settings work for NSSM (`nssm install PromptVault <path-to-promptvault.exe> serve --host localhost --port 8080`, then set `AppDirectory` and optionally `AppEnvironmentExtra` with `PV_DATA_DIR`); NSSM restarts on crash and logs stdout/stderr, which plain Task Scheduler does not.

## Docker as a service

The compose file already ships `restart: unless-stopped` and a health check — for a single-host setup that *is* the service manager:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Updating is `docker compose pull && docker compose up -d` (migrations run at container start; the data volume is upgraded in place).
