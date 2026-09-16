# Aktualizácia existujúcej skúšobnej služby

Cieľ: Render `Dochadzka1`, bezplatný Docker, repozitár `Robo-Miell/Dochadzka`.
Existujúca databáza je PostgreSQL v Neone. Lokálne dáta reportingu sa pri nasadení automaticky neprenášajú.

## Pred nasadením

1. V Neone vytvoriť zálohu/oddelenú vetvu aktuálnej databázy a overiť jej dostupnosť.
2. Na oddelenej testovacej databáze overiť PostgreSQL backend, opakovaný štart, výber zamestnanca, uloženie zákazky/záznamu a exporty.
3. Uchovať pôvodný Git commit nasadenia: `707f025a529fa577b4a763bf95c19a9532e9eb84`.
4. Nahrať len zdrojové súbory, nie `data`, `backups`, `.env` ani lokálne prihlasovacie údaje.

## Ukladanie

Dochádzka používa existujúce tabuľky PostgreSQL. Kvalita vytvorí samostatnú schému `miell_quality` v databáze `DATABASE_URL`. Jej tabuľka používateľov obsahuje iba mapovanie na centrálne účty. Existujúce heslá zostávajú zachované.

Na Renderi zachovať existujúce `DATABASE_URL`, `JWT_SECRET` a ostatné prevádzkové premenné. Bez externého PostgreSQL a stabilného podpisového kľúča aplikácia odmietne štart. `MIELL_DATA_DIR` slúži na dočasné súbory a kópiu zabalenej XLSM šablóny; záznamy kvality sú uložené v PostgreSQL. Trvalý disk nie je potrebný.

## Stav prípravy

SQLite regresné testy prešli. PostgreSQL overenie, záloha a nasadenie ešte musia byť dokončené pred prepnutím služby.
