# ETF Scraper

`etf_monitor.py` continuously checks SEC EDGAR for recent ETF filings and sends
notifications through the configured ntfy topic. It classifies alerts as:

- `New ETF registration`: `N-1A` filings.
- `ETF launch candidate`: `N-2`, `S-1`, and `S-3` filings whose filing document
  contains ETF language.
- `Upcoming ETF listing`: `8-A12B` filings with ETF language and a recognized
  listing exchange. The notification includes that exchange.
- `ETF Section 12(g) registration`: `8-A12G` filings with ETF language. These
  are separate from exchange-listing alerts.

The monitor uses only the Python standard library. Python 3.9 or newer and
network access to `sec.gov` and `ntfy.sh` are required.

## Run Directly

From the repository root:

```bash
python3 src/etf_monitor.py
```

The first successful poll seeds the local seen-filings list without sending
alerts. Leave it running to continue monitoring. Stop it with `Ctrl+C`.

## Run as a systemd Service

Install the tracked service unit, reload systemd, enable it at boot, and start
the updated monitor:

```bash
sudo install -m 644 systemd/etf-monitor.service /etc/systemd/system/etf-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable etf-monitor
sudo systemctl restart etf-monitor
```

Useful service commands:

```bash
systemctl status etf-monitor
sudo systemctl restart etf-monitor
sudo systemctl stop etf-monitor
sudo systemctl start etf-monitor
sudo systemctl disable --now etf-monitor
```

## Logs

Follow live logs:

```bash
journalctl -u etf-monitor -f
```

View today's logs or the latest 50 lines:

```bash
journalctl -u etf-monitor --since today
journalctl -u etf-monitor -n 50
```

## Reset Monitor State

The monitor records seen SEC accession numbers in `~/.etf_seen.json`. Delete
that file to make the next run seed a fresh baseline:

```bash
rm ~/.etf_seen.json
```

## Configuration

At the top of `src/etf_monitor.py`, set `USER_AGENT` to a contactable identity
and set `NTFY` to the ntfy topic that should receive alerts. `POLL` controls
the polling interval in seconds, while `DAYS` controls the SEC search window.
