# Wario Land 4 — traducció al català

Traducció al català de *Wario Land 4* feta a partir de la versió anglesa
(USA/Europa), per **Guillem Roca Castany**. El resultat es distribueix com a pedaç **BPS**:
[`warioland4_ca.bps`](warioland4_ca.bps).

## Aplicar el pedaç

Cal la ROM original **Wario Land 4 (USA, Europe)**:

| | |
|---|---|
| Mida | 8 388 608 bytes |
| MD5 | `5fe47355a33e3fabec2a1607af88a404` |
| CRC32 | `d6141609` *(comprovat pel pedaç)* |

Es pot aplicar amb qualsevol eina compatible amb BPS (Flips, beat, Rom Patcher JS…)
o amb l'script inclòs:

```sh
python3 localization/ca/apply_patch.py baserom_us.gba warioland4_ca.gba
```

## Què s'ha traduït

- **Textos de la font del joc** (`strings_ca.toml`): noms dels passadissos, dels
  nivells i dels caps, títols dels CD de la Sala de So, missatges de la botiga
  d'objectes i de la botiga de minijocs, i "SENSE DADES" a la selecció d'arxiu.
  S'hi han afegit les lletres `à è é í ï ò ó ú ü ç · ,`.
- **Gràfics amb text** (`graphics_ca.toml`):
  - pantalla de títol (PREM START);
  - introducció: titular, text i subtítol del diari, i subtítol del cartell de
    bistecs de la segona variant;
  - selecció d'arxiu (ARXIU, ESBORRAR, SURT, Difícil, Extrem);
  - pantalla d'esborrar dades i els seus diàlegs;
  - pausa (TORNA / SURT / ABANDONA, MÀX i els dos diàlegs);
  - avís de desat després del primer nivell;
  - botigues, Sala de So i minijocs (SURT, MENÚ, REGAL, 1 JOC, MÀX, MIRA);
  - capçaleres dels crèdits, amb una pàgina final nova: "TRADUCCIÓ AL
    CATALÀ — GUILLEM ROCA CASTANY";
  - final del joc ("Gràcies, WARIO...", "UNS DIES DESPRÉS…", el cartell
    "BISTECS! / Menja'n a dojo!!" i la pantalla final "FI" amb "PREM START");
  - combats contra els caps: "TEMPS ESGOTAT" quan s'acaba el temps (també
    al Passadís Daurat), el rètol "BOTIGA" i la pausa "PAUSA" dels passadissos
    dels caps;
  - minijocs: "FI DEL JOC" i "COMENÇA!" als tres minijocs, "A JUGAR!" als
    Home Runs de Wario i el logotip "mini Joc" de la previsualització;
  - El Gran Tauler: caselles "INICI" i "META" del tauler (i les seves
    versions en sprite), rètols "TEU!", insígnies "NOU!" i les estrelles
    "CAP A LA META";
  - Zona de Pinball: les onomatopeies pintades a la paret, adaptades a la
    grafia dels còmics en català ("BRRUM!", "BRM", "NYIIIIIC").
- **Glossari** de termes: [`GLOSSARI.md`](GLOSSARI.md).

Es mantenen en l'original els noms propis (Wario, Nintendo, el personal dels
crèdits), la lletra del karaoke (japonès romanitzat), els termes de beisbol
(STRIKE, OUT, FOUL, HOMERUN), "START" com a nom de botó, el preu "$10" del
cartell de bistecs i les portades dels CD de la Sala de So (noms de grups
inventats). També es mantenen
"Nintendo Presents" i "© 2001 Nintendo". Alguns gràfics sense ús a la versió
USA/Europa (selector d'idioma ENGLISH/JAPANESE, "Start / Cancel", "Press
PUSH") no s'han tocat.

La traducció s'ha revisat jugant amb una partida desada al 100 %: tots els
passadissos (també la Piràmide Daurada i el Passadís Daurat), els 18 nivells,
caps (incloent-hi el temps esgotat), botigues, els tres minijocs de principi a
fi, Sala de So, final i crèdits.

## Regenerar el pedaç

Només cal Python 3.11 o posterior (biblioteca estàndard).

```sh
# des de l'arrel del repositori, amb baserom_us.gba al mateix lloc
python3 localization/ca/build.py
```

Escriu `build/ca/warioland4_ca.gba` i torna a generar `warioland4_ca.bps`. Abans
d'escriure-hi, comprova que el pedaç aplicat sobre la ROM original reprodueix
exactament la ROM traduïda.

## Organització

| Fitxer | Contingut |
|---|---|
| `build.py` | Punt d'entrada: aplica textos i gràfics i genera el BPS |
| `apply_patch.py` | Aplica un BPS a una ROM (sense dependències) |
| `strings_ca.toml` | Cadenes de text: anglès original (es verifica) → català |
| `graphics_ca.toml` | Textos dels gràfics, diàlegs i crèdits |
| `GLOSSARI.md` | Glossari de termes |
| `lib/font.py` | Codificació de text i lletres accentuades de la font 8×16 |
| `lib/graphics.py` | Redibuixat dels gràfics amb text |
| `lib/bitmapfonts.py` | Fonts petites en ASCII-art calcades de l'estil original |
| `lib/art_masks.py` | Lletres pre-rasteritzades (cartell de bistecs, estrelles del Gran Tauler, grafits de la Zona de Pinball) |
| `tools/make_masks.py` | Regenera `art_masks.py` (cal Pillow i la font Inter) |
| `lib/lz77.py`, `lib/rle.py` | Compressió LZ77 (BIOS) i RLE de tilemaps de WL4 |
| `lib/bps.py` | Creació i aplicació de pedaços BPS |
| `lib/romspace.py` | Espai lliure de la ROM i reapuntament de punters |

### Notes tècniques

- Les cadenes ocupen ranures fixes de 26 caràcters (`Shop_DrawText`); la
  traducció s'escriu al mateix lloc, centrada o alineada a l'esquerra com
  l'original.
- La versió USA/Europa fixa `gLanguage = 0` en arrencar, de manera que els textos
  japonesos no es mostren mai. Les lletres accentuades ocupen les caselles de
  les kanes petites `0x6C–0x77`. Les caselles buides `0xF3–0xFE` no serveixen:
  la selecció d'arxiu fa servir algunes d'aquestes tiles buides de farciment.
- La versió anglesa no mostrava la darrera pàgina dels crèdits (la de la nota de
  drets d'autor): el codi la saltava quan `gLanguage = 0`. El pedaç canvia
  aquesta comprovació (`0x94AEC`) perquè es mostri, i hi posa el crèdit de la
  traducció en lloc de la nota.
- Els rètols dels nivells (botiga dels caps, El Gran Tauler, Zona de Pinball) formen part dels
  tilesets: es redibuixen a partir dels blocs 16×16 que els fan servir i es
  comprova que cap tile compartit no quedi dibuixat de dues maneres.
- Els diàlegs es dibuixen amb la mateixa font 8×16 i l'espaiat proporcional
  dels originals. Els gràfics comprimits (LZ77/RLE) es recomprimeixen; si no
  caben al lloc original, es mouen a l'espai lliure del final de la ROM i se'n
  reapunten les referències.
