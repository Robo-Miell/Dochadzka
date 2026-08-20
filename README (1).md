# Dochádzka Online v3

MVP projekt obsahuje:

- **Server/API:** FastAPI
- **Databáza:** PostgreSQL
- **Admin web:** responzívne HTML/JS rozhranie
- **Mobil:** Flutter zdrojový projekt pre Android/iOS
- **Nasadenie:** Docker Compose

## Funkcie

### Admin
- prihlásenie
- vytváranie prevádzok
- vytváranie zamestnancov
- osobné číslo
- login + heslo
- aktivácia/deaktivácia účtu
- prehľad dochádzky
- schválenie/zamietnutie záznamu
- export CSV podľa dátumu, zamestnanca a prevádzky

### Zamestnanec
- vlastný login
- vidí iba svoju dochádzku
- zadá Prácu, Dovolenku, Lekára, PN, OČR, Náhradné voľno alebo Iné
- pri práci zadá Od / Do / prestávku
- môže zvoliť prevádzku
- jeho záznam čaká na schválenie adminom

## Lokálne spustenie servera cez Docker

1. Nainštaluj Docker Desktop alebo Docker Engine.
2. Skopíruj `.env.example` na `.env`.
3. Zmeň `JWT_SECRET` a admin heslo.
4. Spusti:

```bash
docker compose up -d --build
```

Admin web:
`http://localhost:8000/admin`

API dokumentácia:
`http://localhost:8000/docs`

Predvolený admin z `.env.example`:
- login: `admin`
- heslo: `admin123`

## Nasadenie na server

Najjednoduchšie je použiť Ubuntu VPS (napr. Hetzner, DigitalOcean, OVH alebo iný poskytovateľ).

Na VPS:
1. nainštalovať Docker + Docker Compose
2. nahrať tento projekt
3. vytvoriť `.env`
4. spustiť `docker compose up -d --build`
5. pred server dať HTTPS reverse proxy (Caddy/Nginx/Traefik)
6. nastaviť DNS domény, napr. `dochadzka.firma.sk`

Aplikácia je pripravená tak, aby API a admin web bežali z jedného servera.

## Flutter aplikácia

V tomto prostredí nie je nainštalovaný Flutter SDK, preto ZIP obsahuje zdrojový Flutter projekt, ale nie hotové podpísané APK/IPA.

Na počítači s Flutter SDK:

```bash
cd mobile_flutter
flutter create . --platforms=android,ios
flutter pub get
flutter run --dart-define=API_URL=https://dochadzka.firma.sk
```

Android release:

```bash
flutter build apk --release --dart-define=API_URL=https://dochadzka.firma.sk
```

iOS release vyžaduje macOS + Xcode + Apple Developer účet:

```bash
flutter build ipa --release --dart-define=API_URL=https://dochadzka.firma.sk
```

## Dôležité pred ostrou prevádzkou

Toto je funkčný MVP základ, nie finálny auditovaný dochádzkový/mzdový systém. Pred ostrým použitím odporúčam doplniť najmä:
- HTTPS a doménu
- pravidelné zálohy PostgreSQL
- audit log zmien
- reset hesla
- silnejšiu password policy
- ochranu proti opakovaným login pokusom
- GDPR/retenciu údajov
- uzatváranie mesiaca
- presné firemné pravidlá pre fond hodín, sviatky, nadčasy a absencie
