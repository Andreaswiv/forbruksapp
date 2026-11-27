# Forbruksapp

Lokal app som leser kontoutskrifter fra norske banker (CSV/Excel) og viser hva pengene går til. Den finner også abonnementer og unødvendig forbruk, sammenligner med SIFO-referansebudsjettet, lager budsjett og prognoser, og gir deg en månedsrapport som PDF.

**Alt kjører og lagres lokalt på maskinen din.**

## Kom i gang

```bash
cd ~/Dokumenter/forbruksapp
./start.sh
```

Første gang lager `start.sh` et virtuelt Python-miljø (`.venv`) og installerer pakkene. Appen åpner seg på http://localhost:8501.

Manuelt:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Vil du teste uten egne data, trykk **Last inn eksempeldata** på forsiden. Eksempelfilene ligger i `eksempeldata/`, og du lager dem på nytt med `python eksempeldata/lag_eksempeldata.py`.

## Slik bruker du den

1. **Last ned transaksjoner** fra nettbanken (CSV eller Excel), gjerne flere måneder om gangen.
2. **Last opp** filene og velg hvilken konto de hører til. Opprett kontoen første gang. Legg inn kontonummeret, så kjenner appen igjen overføringer mellom egne kontoer.
3. Gå til **Kategorier og regler → Ukategorisert** og gi de ukjente butikkene en kategori. Reglene huskes til neste gang.
4. Se på **Oversikt**, **Abonnementer**, **Tullball og prognoser**, **SIFO** og **Budsjett**.
5. Last opp en ny fil hver måned. Overlappende perioder er ikke noe problem, fordi duplikater hoppes over.

## Funksjoner

| Side | Hva den gjør |
|---|---|
| Oversikt | Inn, forbruk, sparing og netto per periode, forbruk per kategori, topp 10 steder, avvik og utvikling over tid |
| Last opp | CSV/Excel fra DNB, Nordea, SpareBank 1, Sbanken, Bulder m.fl. Kjenner igjen kolonnene automatisk, ellers velger du selv (valget huskes per bankformat). Du kan slette enkeltopplastinger |
| Transaksjoner | Søk og filtrer, endre kategori, marker overføringer og felles utgifter, lag regler |
| Kategorier og regler | Kategoriser ukjente butikker i bulk, se og slett regler, valgfrie AI-forslag |
| Abonnementer | Finner faste trekk automatisk (ukentlig til årlig) og viser en «Si opp?»-liste med løpende besparelse, prisøkninger, overlapp og trekk som har stoppet |
| Tullball og prognoser | Tullball-detektor med konkrete sparebeløp, avvik mot vanlig nivå, «hva om»-simulering og kontantstrøm-prognose til neste lønning |
| SIFO | Sammenligning med SIFO-referansebudsjettet for husholdningen din, med koblingen mellom kategoriene dine og SIFO-postene |
| Budsjett | Forslag basert på snittet ditt og SIFO, 50/30/20-sjekk, oppfølging per periode og eksport til Excel |
| Månedsrapport | PDF for én periode, enten «Bare meg» eller «Felles økonomi» (hvem har betalt hva, og hvem skylder hvem) |
| Innstillinger og personvern | Kontoer, lønningsdag, AI av/på, slett en periode og **slett alle data** |

I sidepanelet velger du mellom **kalendermåned** og **lønn til lønn**. Lønn-til-lønn bruker den faktiske lønnsdatoen når den finnes, for eksempel fredag før helg.

## Personvern

- Databasen og rapportene ligger i `~/.forbruksapp/` (en annen mappe kan settes med miljøvariabelen `FORBRUKSAPP_DIR`).
- Appen lytter bare på `localhost`, og Streamlits bruksstatistikk er skrudd av i `.streamlit/config.toml`.
- **AI-kategorisering er av som standard.** Når du slår den på, sendes bare butikknavn til Claude (Anthropic). Beløp, datoer, kontonumre og Vipps-/overføringstekster som kan inneholde personnavn sendes ikke. Du ser hva som sendes før du trykker, og forslagene må godkjennes. Funksjonen krever `ANTHROPIC_API_KEY` eller `ant auth login`.
- **Slett alle data** (under Innstillinger) sletter databasen og alle genererte rapporter.

## Oppdatere SIFO-tall

`data/sifo_satser.json` inneholder de **offisielle tallene for 2026** fra SIFO-rapport 9-2026 (regnearket `Referansebudsjettet_2026_Norsk.xlsx`, https://hdl.handle.net/11250/5517284). SIFO oppdaterer tallene hvert år, vanligvis i juni. Slik legger du inn nye tall:

1. Åpne årets SIFO-rapport i Nasjonalt vitenarkiv (lenket fra SIFOs side om referansebudsjettet på oslomet.no), og åpne Excel-filen.
2. Fanen «Individspes. utgifter» → `individ`. Hver post har en liste med `alder_fra`, `alder_til`, `kjønn` (`alle`, `kvinne` for K/J eller `mann` for M/G) og `beløp`. Endre beløpene, og aldersgruppene hvis SIFO har endret dem.
3. Fanen «Husholdsspes. utgifter» → `husholdning` (beløp per antall personer) og `bil` (`bensin`/`el`, for 1–4 og 5–7 personer).
4. Oppdater `år` og `kilde`.
5. Kjør testene. `test_sifo_matches_official_example_family` sjekker mot SIFOs eksempelfamilie og må oppdateres med årets tall.

SIFO dekker ikke bolig, lån, restaurant, alkohol eller ferie. Disse vises som «Ikke med i SIFO» i appen.

## Regler for kategorisering

- `rema 1000` må stå som eget ord eller uttrykk i teksten.
- `lønn*` treffer alt som begynner med «lønn».
- `re:^giro \d+` er et regulært uttrykk.

Prioritet: dine egne regler, så godkjente AI-forslag, så innebygde regler, og til slutt generelle regler (Vipps). Transaksjoner du har endret manuelt, røres aldri.

## Duplikater

Hver transaksjon får en nøkkel av konto, dato, beløp og tekst. Like nøkler i samme fil nummereres (1, 2, 3 …), så to like kaffekjøp samme dag lagres som to kjøp. En ny fil med de samme to kjøpene gir likevel ikke fire.

## Tester

```bash
.venv/bin/python -m pytest
```

## Struktur

```
app.py                     Streamlit-grensesnittet
forbruk/
  importer.py              Innlesing av CSV/Excel (skilletegn, tegnkoding, tall, datoer, kolonner)
  db.py                    SQLite-lagring og duplikatsjekk
  categorize.py            Regler, butikknøkler og overføringer mellom egne kontoer
  subscriptions.py         Abonnementsjeger
  analysis.py              Perioder, oppsummering, avvik, hva om, prognose, tullball-detektor
  sifo.py                  SIFO-sammenligning
  budget.py                Budsjettforslag, oppfølging, felles økonomi, Excel-eksport
  report.py                PDF-rapport
  ai_categorize.py         Valgfri AI-kategorisering (av som standard)
data/sifo_satser.json      SIFO-satser (eksempeltall – oppdater!)
eksempeldata/              Falske kontoutskrifter i fire filer og tre bankformater
tests/                     pytest
```
