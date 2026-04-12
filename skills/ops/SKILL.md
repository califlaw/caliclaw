---
name: ops
description: SSH, systemd, logs, deploy, rollback
audience: devops
---

## Ops

Server operations like a senior. Boring infrastructure that just works.

**Critical: you run without a terminal.** You cannot answer interactive prompts (passwords, y/n confirms, sudo). Always use non-interactive flags: `ssh -o BatchMode=yes`, `apt-get -y`, `sshpass` for password auth, `DEBIAN_FRONTEND=noninteractive` for apt. If a command will hang waiting for input — find the non-interactive alternative first.

### SSH

You run non-interactively — you CANNOT type passwords or answer interactive prompts. Plan accordingly.

**Connecting:**
- **Prefer SSH keys** — `ssh-keygen -t ed25519` then `ssh-copy-id user@host`. After that `ssh user@host` works without passwords.
- If keys aren't set up yet and you need password auth: use `sshpass -p 'pass' ssh user@host`. If `sshpass` is missing, tell the user to run `sudo apt install sshpass` or set up keys.
- NEVER try raw `ssh user@host` if it requires a password — it will hang forever because you have no terminal for input.
- Use `-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10` to avoid interactive prompts on first connect.
- Use `~/.ssh/config` aliases instead of typing full hosts:
  ```
  Host myserver
    HostName 192.168.0.105
    User root
    IdentityFile ~/.ssh/id_ed25519
  ```
- For file transfers: `scp -r user@host:/path /local/path` or `rsync -avz`.

**Security:**
- One key per machine, not one master key everywhere.
- For production: `PasswordAuthentication no` in sshd_config.
- `ssh-agent` for unlocked keys, never store passphrase in plaintext.

### systemd

- Service files in `/etc/systemd/system/<name>.service`
- `systemctl status <svc>` — check state + last logs
- `journalctl -u <svc> -f` — follow logs in real time
- `journalctl -u <svc> --since "1 hour ago"` — time filter
- Restart loops? Check `systemctl status` for `Restart=on-failure` count
- Always `daemon-reload` after editing service files

### Logs

- Know where logs live: `journalctl`, `/var/log/`, app-specific dirs
- **Don't `tail -f` to disk** — fills up. Use `journalctl -f` or rotate.
- Structured logs > plain text. JSON if possible.
- `logrotate` configured for every long-running service.

### Resource analysis

- `htop` for CPU/RAM at a glance
- `iotop` for disk I/O bottlenecks
- `df -h` and `du -sh /*` to find disk hogs
- `free -h` for memory pressure
- `ss -tlnp` for what's listening on what port
- `vmstat 1` for system-wide pulse

### Deploy

- **Blue-green over in-place**: deploy new instance, switch traffic, kill old
- **Always have rollback plan** — and test it before you need it
- **Health checks before traffic** — load balancer should verify the new instance
- Database migrations run BEFORE deploying code, not during
- Keep old version's binary/image for 24h minimum

### Don't

- Run services as root
- Edit config in production with `vim` — use config management
- `kill -9` a database (data corruption)
- Disable swap "for performance" without understanding consequences
- Manual deploys at 5 PM on Friday
