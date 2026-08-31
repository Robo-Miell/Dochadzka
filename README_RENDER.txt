MIELL DOCHÁDZKA – VERZIA 4
==========================

BACKEND / WEB ADMIN
-------------------
Do GitHub repozitára pre Render nahraj:
- main.py
- admin.html
- brand.png
- requirements.txt
- render.yaml

Render nastavenie:
Root Directory: prázdne
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT

Environment Variables:
DATABASE_URL = connection string databázy
ADMIN_LOGIN = admin
ADMIN_PASSWORD = tvoje admin heslo
ADMIN_NAME = Administrátor
JWT_EXPIRE_MINUTES = 10080
ALLOWED_ORIGINS = *
JWT_SECRET = dlhý náhodný tajný reťazec

Admin rozhranie:
https://dochadzka1.onrender.com/admin

NOVÉ VO VERZII 4
----------------
Admin môže:
- upravovať zamestnanca: osobné číslo, meno, login, heslo, prevádzku, aktivitu
- odstrániť zamestnanca, ak nemá dochádzkové záznamy
- upravovať názov, mesto a adresu prevádzky
- odstrániť nepoužitú prevádzku
- vytvárať dochádzku za zamestnanca
- upravovať dátum, zamestnanca, prevádzku, typ, čas od/do, prestávku, poznámku a stav
- odstrániť jednotlivý dochádzkový záznam

Dôležité: zmeny endpointov nevyžadujú zmenu databázových tabuliek, takže existujúce dáta ostávajú zachované.
