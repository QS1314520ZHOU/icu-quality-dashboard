# ICU Quality Dashboard OEL 8.2 Binary Package

This package contains one executable binary with the backend API and frontend static files bundled together.

## Files

- `icu-quality-dashboard`: executable binary
- `.env.template`: runtime configuration template
- `README.md`: this guide

## Install

```bash
tar -xzf icu-quality-dashboard-oel8.2-x86_64.tar.gz
cd icu-quality-dashboard
cp .env.template .env
vi .env
```

Fill the MongoDB and LLM settings in `.env`.

## Run

```bash
chmod +x ./icu-quality-dashboard
./icu-quality-dashboard
```

Open:

```text
http://SERVER_IP:8091
```

Health check:

```bash
curl http://127.0.0.1:8091/api/departments
```

## Systemd Example

Create `/etc/systemd/system/icu-quality-dashboard.service`:

```ini
[Unit]
Description=ICU Quality Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/icu-quality-dashboard
ExecStart=/opt/icu-quality-dashboard/icu-quality-dashboard
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo mkdir -p /opt/icu-quality-dashboard
sudo cp -a icu-quality-dashboard/* /opt/icu-quality-dashboard/
sudo systemctl daemon-reload
sudo systemctl enable --now icu-quality-dashboard
sudo systemctl status icu-quality-dashboard
```

## Notes

- The binary reads `.env` from the executable directory first.
- The frontend is served by the same process as the backend.
- API routes are under `/api`.
