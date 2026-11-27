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

Vil du teste uten egne data, trykk **Prøv med eksempeldata** på forsiden. Eksempeldataene er en 20 år gammel student («Emma Hansen») med deltidsjobb, stipend fra Lånekassen og en del abonnementer. Filene ligger i `eksempeldata/`, og du lager dem på nytt med `python eksempeldata/lag_eksempeldata.py`.

## Slik bruker du den

1. **Skriv navnet ditt** (fullt navn, slik det står i banken). Da forstår appen at «Overføring til Emma Hansen» eller «Fra: Emma Hansen» er deg som flytter penger mellom egne kontoer, og ikke forbruk eller inntekt. Bare fornavn er ikke nok, fordi en venn med samme fornavn da kunne blitt tolket som deg.
2. **Last opp** kontoutskriften fra nettbanken (CSV eller Excel), gjerne 3–6 måneder. Velg hvilken konto filen hører til.
3. Appen spør om butikker den ikke kjenner («Hva er X?»). Svaret huskes til neste gang.
4. Last opp en ny fil hver måned. Overlappende perioder er ikke noe problem, fordi duplikater hoppes over.

## Sidene

| Side | Hva den viser |
|---|---|
| Hjem | Brukt, fått inn, spart og igjen denne måneden, hvor pengene gikk, tre tips og utviklingen måned for måned |
| Pengene mine | Kategorier som smultring og liste, og alle kjøp. Trykk på en kategori for å endre den |
| Abonnementer | Hva du betaler i måneden og året, prisøkninger, overlapp (f.eks. tre strømmetjenester) og «Beholde / Usikker / Si opp» med utregnet besparelse |
| Budsjett | **📝 Planlegg** neste (eller denne) måned i fem steg: hva du får inn, faste utgifter (funnet automatisk), egne planer (bursdag, konsert …), hvor mye du vil spare, og forslag til resten. Forslaget kutter mest i «ønsker» hvis pengene ikke strekker til. **📊 Slik går det** viser planen mot det du faktisk har brukt, og hvor mye du kan bruke per dag. Kan lastes ned som Excel |
| Innsikt | Sparetips, sammenligning med SIFO for noen på din alder, «hva om»-spaker, prognose fram til lønning og månedsrapport som PDF |
| Last opp | Slipp filer fra DNB, Nordea, SpareBank 1, Sbanken, Bulder m.fl. Kolonnene kjennes igjen automatisk |
| Innstillinger | Navnet ditt, kontoer (en sparekonto teller som sparing), opplastede filer, kalendermåned eller lønn til lønn, det du har lært appen, AI av/på og **slett alle data** |

## Personvern

- Databasen og rapportene ligger i `~/.forbruksapp/` (en annen mappe kan settes med miljøvariabelen `FORBRUKSAPP_DIR`).
- Appen lytter bare på `localhost`, og Streamlits bruksstatistikk er skrudd av i `.streamlit/config.toml`.
- **AI-hjelp er av som standard.** Se «AI-hjelp fra Claude» under.
- **Slett alle data** (under Innstillinger) sletter databasen og alle genererte rapporter.

## AI-hjelp fra Claude

Claude kan foreslå kategorier for butikker appen ikke kjenner. Slå det på under **Innstillinger → AI-hjelp fra Claude**. Hver person bruker sin egen Claude, og det trengs ingen API-nøkkel.

**Tre måter å bruke det på:**

1. **Claude-appen på PC-en (Claude Desktop).** Trykk **Koble til Claude** og start Claude på nytt. Skriv så for eksempel «Hjelp meg å kategorisere utgiftene mine i Pengene mine». Appen er en liten MCP-server (`mcp_server.py`) med to verktøy: `hent_ukjente_utgifter` og `lagre_kategorier`. Knappen legger den inn i `claude_desktop_config.json`. Andre innstillinger beholdes, og det lages en sikkerhetskopi (`.json.bak`).
2. **Rett i appen.** Hvis Claude Code finnes på maskinen (`claude`-kommandoen, eller den som følger med Claude-appen), kan du trykke **La Claude foreslå kategorier**. Du ser forslagene og godkjenner dem før de lagres. Appen bruker modellen «sonnet», med «haiku» som reserve.
3. **Claude Code i terminalen.** Kommandoen for å legge til MCP-serveren står i appen.

Med `ANTHROPIC_API_KEY` satt kan appen også bruke Claude-API-et direkte.

**Hva Claude får se.** Bare anonymisert butikktekst, og om pengene gikk inn eller ut. Under Innstillinger kan du se nøyaktig hva som blir sendt.

- Beløp, datoer, kontonumre, kortnumre, telefonnumre, e-post og nettadresser sendes aldri.
- **Personnavn anonymiseres fullstendig** (`forbruk/anonymize.py`):
  - Alt etter «Vipps», «Fra:», «Til:», «Overføring til», «Betaling til» o.l. regnes som et personnavn, med mindre det er en kjent butikk eller ser ut som et firma («AS», «kafé» …).
  - Kjente fornavn (norske og vanlige utenlandske) fjernes hvor som helst i teksten, sammen med alle etternavn ved siden av, også med STORE bokstaver.
  - To eller flere ord på rad som ser ut som navn («Olai Bergh»), skjules selv om fornavnet ikke er kjent.
  - Etter «SumUp», «Zettle» o.l. skjules resten, fordi små butikker ofte står oppført med eierens navn.
  - Navnet ditt blir «Deg selv».
  - Personer blir «Person 1», «Person 2» …, og den samme personen får samme nummer. Koblingen til det ekte navnet forlater aldri maskinen.
- Hver linje sendes med en tilfeldig id. Svaret kobles tilbake lokalt.
- MCP-serveren nekter å gi ut noe når AI-hjelp er slått av i appen. Etter en oppdatering av appen må Claude startes på nytt, så serveren får den nye koden.
- Kategorier fra Claude lagres som regler med kilde «ai», som du kan se og fjerne under «Det du har lært appen».

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

Reglene lages automatisk når du svarer på «Hva er X?». Prioritet: dine egne regler, så godkjente AI-forslag, så innebygde regler, og til slutt generelle regler (Vipps). Transaksjoner du har endret manuelt, røres aldri.

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
  budget.py                Oppfølging mot budsjett, felles økonomi, Excel-eksport
  plan.py                  Månedsplan: inntekt, faste utgifter, egne planer, sparing og forslag til resten
  report.py                PDF-rapport
  ai_categorize.py         AI-hjelp med Claude (av som standard)
  anonymize.py             Anonymisering av navn og tall før noe sendes
  claude_connect.py        Kobler appen til Claude Desktop
mcp_server.py              MCP-server for Claude Desktop / Claude Code
data/sifo_satser.json      Offisielle SIFO-satser 2026
eksempeldata/              Falske kontoutskrifter i fire filer og tre bankformater
tests/                     pytest
```
