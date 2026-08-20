# Render + Neon: presný postup

## 1. Neon databáza

1. Otvor https://console.neon.tech a vytvor bezplatný účet.
2. Vytvor nový projekt, napr. `dochadzka`.
3. Vyber európsky región, ak je dostupný.
4. V časti **Connection Details** zvoľ **Pooled connection**.
5. Skopíruj connection string. Vyzerá približne:
   `postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/neondb?sslmode=require`

Tento reťazec obsahuje heslo. Nikomu ho neposielaj a neukladaj ho do GitHub repozitára.

## 2. GitHub

1. Vytvor účet na https://github.com, ak ho ešte nemáš.
2. Vytvor nový **Private** repository, napr. `dochadzka`.
3. Nahraj do koreňa repozitára obsah tohto priečinka.
   Dôležité: `render.yaml` musí byť v koreňovom adresári.

## 3. Render

1. V Render Dashboard klikni **New > Blueprint**.
2. Pripoj GitHub a vyber repository `dochadzka`.
3. Render načíta `render.yaml`.
4. Pri vytváraní doplň tajné premenné:
   - `DATABASE_URL` = pooled connection string z Neonu
   - `ADMIN_PASSWORD` = tvoje nové silné admin heslo
5. `JWT_SECRET` Render vytvorí automaticky.
6. Potvrď vytvorenie služby.

Po deployi dostaneš adresu podobnú:
`https://dochadzka-xxxx.onrender.com`

Admin:
`https://dochadzka-xxxx.onrender.com/admin`

API dokumentácia:
`https://dochadzka-xxxx.onrender.com/docs`

## 4. Prvé prihlásenie

Admin login je:
`admin`

Heslo je hodnota, ktorú si vložil do `ADMIN_PASSWORD`.

Pri prvom štarte server vytvorí databázové tabuľky a admin účet automaticky.

## 5. Mobilná aplikácia

Pri Android/iOS builde nastav API URL na Render adresu bez `/admin`, napr.:

`https://dochadzka-xxxx.onrender.com`

Android:
`flutter build apk --release --dart-define=API_URL=https://dochadzka-xxxx.onrender.com`

## Poznámka k Free Render

Free Web Service sa po 15 minútach bez prichádzajúcej prevádzky uspí. Prvý request po uspávaní môže trvať približne minútu. Dáta zostávajú v Neone.
