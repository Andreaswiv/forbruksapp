"""Fjerner alt som kan peke på en person før tekst sendes til en AI.

Prinsippet er «heller for mye enn for lite»:
- Navnet ditt fjernes alltid.
- Etter ord som «Vipps», «Fra:», «Til:», «Overføring til» o.l. regnes resten som et
  personnavn, med mindre det er en kjent butikk eller ser ut som et firma (AS, kafé …).
- Kjente fornavn fjernes hvor som helst i teksten, sammen med ord med stor forbokstav
  rett ved siden av (etternavn).
- Tall (kontonummer, kortnummer, telefon, datoer, beløp), e-post og nettadresser fjernes.

Personer erstattes med «Person 1», «Person 2» … Den samme personen får samme nummer
innenfor én forespørsel, så AI-en kan se at flere betalinger går til samme person,
men aldri hvem det er. Koblingen mellom nummer og navn forlates aldri maskinen.
"""
from __future__ import annotations

import re

# Vanlige fornavn i Norge (SSB) og noen internasjonale. Små bokstaver.
FIRST_NAMES = set("""
emma nora sara sofie olivia sofia ella maja ingrid emilie leah thea frida ida tiril hedda vilde
amalie anna aurora selma mia hanna hannah julie jenny ingeborg mathilde marie maria astrid sigrid
eva linnea live mille oda kaja karoline kristine kari anne inger liv berit randi solveig
ragnhild hilde marit grete gro tone tove heidi silje camilla ane marte martine stine lene line
mette nina ellen elin elise eli ida helene hege kristin kirsten guro siri synne tuva victoria
viktoria wenche turid unni torill bente bodil birgit ann anita ase åse benedikte cecilie charlotte
christine elisabeth eline emilie frøya helle henriette idun ina iselin janne johanne josefine
julia karen katrine lea lisa louise malin margrethe mari marianne mina mona monica monika
nathalie pernille rebecca rebekka ronja ruth sandra sanna signe sunniva susanne therese tina
torunn trine vibeke yvonne amanda andrea alma alva agnes aisha fatima hiba amina zahra
jakob jacob emil noah oliver filip william lucas lukas liam henrik oskar oscar aksel axel theodor
elias kasper isak magnus johannes mathias matias sander jonas tobias adrian olav ola kari
håkon haakon martin andreas daniel kristian christian thomas tomas markus marcus ole jan per
bjørn lars knut arne svein kjell hans terje geir odd nils tor trond rune morten espen erik eirik
jon john petter peter stian anders fredrik vegard sindre sigurd sivert even eivind øyvind
gunnar harald halvor helge ivar jørgen jørn kåre leif magne nikolai nicolai pål paul rolf
rasmus robert roger sebastian simon steffen stein sverre torbjørn torstein trygve vidar
alexander aleksander benjamin david edvard felix gabriel herman iver jens joakim johan jonathan
josef kevin leon ludvig mats max mikkel mohammed muhammad ahmed ali omar hassan hussein
mustafa yusuf ibrahim adam aron august brage birk colin dennis eskil finn frank gustav hugo
idar jostein kenneth kim kristoffer krister lasse marius mads ruben samuel tor-arne viktor
victor vebjørn vetle tage teodor storm odin aleksandra ewa piotr tomasz anna-lena
giulia francesca chiara federica valentina alessandra roberta paola giovanna lucia elena silvia
marco luca giuseppe giovanni francesco alessandro andrea matteo lorenzo stefano roberto antonio
paolo davide simone riccardo fabio massimo
ivan georgi dimitar nikolay petar stoyan todor hristo nasko milen ivelin valentin boris
maria-elena desislava gergana yana mariya petya tsvetelina
md mohammad mohamed mohammed muhammed abdul abdullah rahman rahim karim kamal hasan hossain hossein
anower anwar rafiq shafiq zahirul nazrul aminul rezaul mizanur jahangir habib sumon shahid faruk
layla leila laila nadia samira yasmin jasmin fatma aisha ayesha nusrat sultana rina shirin
krzysztof katarzyna agnieszka magdalena joanna marta pawel michal kamil jakub mateusz
olga irina natalia tatiana svetlana sergei sergey dmitri alexei andrei vladimir
juan jose carlos luis miguel javier pablo diego carmen lucia sofia isabel
""".split())

# Ord som tyder på firma/butikk, ikke person
BUSINESS = set("""
as asa ans da sa ba nuf enk ab aps oy gmbh ltd inc llc co bv sarl spa srl
butikk butikken shop store senter senteret kafe kafé cafe café bar pub restaurant sushi pizza
kiosk bakeri bakeriet frisør salong klinikk tannlege apotek legesenter treningssenter
hotell hotel camping parkering bensin stasjon service verksted kino teater museum
forening klubb lag idrettslag borettslag sameie kommune fylke stat skole universitet
gruppen group holding invest eiendom norge norway nordic scandinavia online nettbutikk
klarna revolut paypal apple google microsoft airlines airline air booking ticket tickets travel reiser
pizzeria trattoria osteria ristorante supermercato supermarket minimarket gelateria bakery coffee
taxi transport sport sports fitness gym mat food market marked auto design studio bistro grill burger
burgers kebab optikk interiør blomster bokhandel elektro sko klær mote fashion beauty hair nails city
center centre outlet express energi strøm forsikring bank sparebank pay payments lotteri tipping
""".split())

# Små ord som hører til navn («van der Berg», «Mc Dermott»)
PARTICLES = {"van", "von", "der", "den", "de", "da", "di", "del", "la", "le", "mc", "mac", "af", "bin", "al"}
# Et ord som ser ut som et navn: stor forbokstav, resten små («Bergh», «Støa-Helland»)
_NAME_WORD = re.compile(r"^[A-ZÆØÅÄÖÜÉÈ][a-zæøåäöüéèáíóúñç]+(?:-[A-ZÆØÅÄÖÜÉÈ][a-zæøåäöüéèáíóúñç]+)*[.,]?$")

# Ord som ofte står foran navnet på en privatperson
PERSON_PREFIX = re.compile(
    r"^\s*(vipps\s*\*?|vipps:|mobilepay\s*\*?|fra:|til:|fra\s|til\s|overføring\s+(til|fra)\s+|overf\.?\s+(til|fra)\s+|"
    r"betaling\s+(til|fra)\s+|straksbetaling\s+(til|fra)\s+|straksoverføring\s+(til|fra)\s+|innbetaling\s+fra\s+|"
    r"giro\s+(til|fra)\s+|nettbank\s+(til|fra):?\s*|from\s+|to\s+)", re.I)

# Kortterminaler for små bedrifter. De er ofte registrert på eieren som privatperson
# («SUMUP OLA NORDMANN»), så resten skjules hvis det ikke ser ut som et firma.
TERMINAL_PREFIX = re.compile(r"^\s*(sumup|zettle_?|izettle|sq|square)\s*[*_]?\s*", re.I)

_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"\b(https?://\S+|www\.\S+)", re.I)
_DIGITS = re.compile(r"[\d*][\d.,:/*\-\s]*\d|\d")
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-zÆØÅæøåÀ-ÿ][A-Za-zÆØÅæøåÀ-ÿ'\-]*")
_NOISE = re.compile(r"\b(nok|kurs|dato|valuta|varekjøp|varekjop|kortkjøp|reservert|visa|mastercard)\b", re.I)


class Anonymizer:
    """Brukes for én forespørsel, slik at samme person får samme nummer."""

    def __init__(self, own_name: str | None = None, known_merchants=None):
        self.own_words = {w.lower() for w in (own_name or "").replace(",", " ").split() if len(w) > 1}
        self.known = known_merchants or (lambda text: False)
        self.people: dict[str, str] = {}

    def _person(self, name: str) -> str:
        words = [w.lower() for w in _WORD.findall(name) if w.lower() not in PARTICLES]
        if words and self.own_words and all(w in self.own_words for w in words):
            return "Deg selv"
        key = " ".join(sorted(words)) or name.lower()
        if key not in self.people:
            self.people[key] = f"Person {len(self.people) + 1}"
        return self.people[key]

    @staticmethod
    def _looks_like_business(words: list[str]) -> bool:
        return any(w.lower().strip(".") in BUSINESS for w in words)

    def anonymize(self, text: str) -> str:
        t = _EMAIL.sub(" ", text)
        t = _URL.sub(" ", t)
        t = _DIGITS.sub(" ", t)
        t = _NOISE.sub(" ", t)
        t = t.replace("*", " * ")
        t = _SPACES.sub(" ", t).strip(" *-.,:")

        # 1) Navnet ditt blir «Deg selv» – det skjer i _person(), sammen med andre navn

        # 2) Alt etter «Vipps», «Til:», «Overføring fra» … er en person, hvis det ikke er en butikk
        m = PERSON_PREFIX.match(t)
        if m:
            rest = t[m.end():].strip(" *:-")
            words = _WORD.findall(rest)
            if rest and words and not self._looks_like_business(words) and not self.known(rest):
                prefix = m.group(0).replace("*", "").strip().rstrip(":").strip()
                prefix = prefix[:1].upper() + prefix[1:].lower() if prefix else ""
                return f"{prefix} {self._person(rest)}".strip()

        m = TERMINAL_PREFIX.match(t)
        if m:
            rest = t[m.end():].strip(" *_:-")
            words = _WORD.findall(rest)
            if rest and words and not self._looks_like_business(words) and not self.known(rest):
                return f"{m.group(1).rstrip('_').capitalize()} {self._person(rest)}"

        # Kjent butikk (f.eks. «HBO Max», «Max Burgers») – ingen navn å skjule
        if self.known(t):
            return t.replace(" * ", " ").strip()

        # 3) Navn: et kjent fornavn, eller minst to ord på rad som ser ut som navn («Olai Bergh»).
        #    Alle navneord rett før og etter tas med, uansett hvor mange etternavn det er.
        tokens = t.split(" ")
        n = len(tokens)

        def is_name_word(k: int) -> bool:
            w = tokens[k]
            return bool(_NAME_WORD.match(w)) and w.strip(".,").lower() not in BUSINESS

        def is_part(k: int) -> bool:
            w = tokens[k].strip(".,").lower()
            return is_name_word(k) or tokens[k].lower() in PARTICLES or w in FIRST_NAMES or w in self.own_words

        out: list[str] = []
        i = 0
        while i < n:
            bare = tokens[i].strip(".,:;()").lower()
            run_end = i
            while run_end < n and is_part(run_end):
                run_end += 1
            run = tokens[i:run_end]
            name_words = [w for w in run if w.lower() not in PARTICLES]
            caps_trigger = bare in FIRST_NAMES and tokens[i].isupper()
            if caps_trigger:
                run_end = i + 1
                while run_end < n and (_caps_name(tokens[run_end]) or tokens[run_end].lower() in FIRST_NAMES):
                    run_end += 1
                run = tokens[i:run_end]
                while out and _caps_name(out[-1]) and out[-1] not in ("Person", "Deg"):
                    run.insert(0, out.pop())
                out.extend(self._person(" ".join(run)).split())
                i = run_end
                continue
            if bare in FIRST_NAMES or bare in self.own_words or (len(name_words) >= 2 and sum(1 for k in range(i, run_end) if is_name_word(k)) >= 2):
                if run_end == i:                      # fornavn skrevet med små bokstaver («kari»)
                    run_end = i + 1
                    run = tokens[i:run_end]
                # Etternavn som står foran («Hansen Emma»)
                while out and _NAME_WORD.match(out[-1]) and out[-1].lower() not in BUSINESS \
                        and out[-1] not in ("Person", "Deg"):
                    run.insert(0, out.pop())
                person = self._person(" ".join(run))
                out.extend(person.split())
                i = run_end
                continue
            out.append(tokens[i])
            i += 1
        # Navneord som står rett etter «Person N» (resten av et langt navn)
        cleaned: list[str] = []
        k = 0
        while k < len(out):
            cleaned.append(out[k])
            if out[k] == "Person" and k + 1 < len(out):
                cleaned.append(out[k + 1])
                k += 2
                while k < len(out) and (_NAME_WORD.match(out[k]) and out[k].strip(".,").lower() not in BUSINESS
                                        or out[k].lower() in PARTICLES):
                    k += 1
                continue
            k += 1
        return _SPACES.sub(" ", " ".join(cleaned)).replace(" * ", " ").strip(" *")


def _caps_name(w: str) -> bool:
    """Et ord med bare store bokstaver som kan være et navn («HOSSAIN»)."""
    return len(w) >= 2 and w.isalpha() and w.isupper() and w.lower() not in BUSINESS


def contains_person(text: str) -> bool:
    return "Person " in text or "Deg selv" in text
