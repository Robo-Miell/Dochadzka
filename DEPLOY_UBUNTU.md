# Rýchle nasadenie na Ubuntu VPS

## 1. DNS
Nasmeruj A záznam napr. `dochadzka.firma.sk` na IP servera.

## 2. Docker
```bash
sudo apt update
sudo apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```
Odhlás/prihlás SSH session.

## 3. Projekt
Nahraj priečinok `dochadzka_online_v3` na server.

```bash
cd dochadzka_online_v3
cp .env.example .env
nano .env
docker compose up -d --build
```

## 4. HTTPS
Odporúčaný reverse proxy je Caddy alebo Nginx. API kontajner počúva na porte 8000.
V ostrej prevádzke nevystavuj databázový port do internetu.

Príklad Caddyfile:
```text
dochadzka.firma.sk {
    reverse_proxy 127.0.0.1:8000
}
```

Potom admin:
`https://dochadzka.firma.sk/admin`

Flutter API URL:
`https://dochadzka.firma.sk`
