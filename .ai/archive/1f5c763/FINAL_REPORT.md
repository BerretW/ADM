# Závěrečný report: Advanced Material and Terrain Integration

## Stav mise

Mise je k 27. listopadu 2026 řízeně uzavřena jako přijatý vývojový základ pro
Advanced Terrain & Physical Surface System. Neznamená to splnění všech původních
požadavků ani nezávislou certifikaci ADM. Nedokončené položky zůstávají
nezaškrtnuté v [checklistu](TASKS.md); příčiny a další postup jsou v
[technickém dluhu](TECHNICAL_DEBT.md).

Zdrojový základ implementace je commit `cd3c9b9`. Dokumenty závěrečného auditu
na něj navazují. Distribuční ZIPy v `dist/` jsou lokální výstupy a nejsou součástí
Git baseline.

## Dokončeno

- Standard a registry obsahují čtyři profily:
  `adm.terrain.four_layer@1.1.0`, `adm.terrain.four_layer@2.1.0`,
  `adm.surface.two_layer@1.1.0` a `adm.pbr.layered@2.1.0`. Starší profily
  zůstávají samostatné. Zdokumentovány jsou AO, height blending, parallax,
  POM a rozšíření `ADM_material_height_v1`.
- Sdílené kodeky a validace podporují R8, R16, BC4, BC5 a BC7 UNORM/SRGB
  v DDS a KTX2. Kompatibilní GPU zdroje a 16bitová data se zachovávají v
  otestovaných cestách; explicitní konverze je oddělená od passthrough.
- World Tile zachovává stávající biome a surface noise, painting, roads,
  projekty, presety a Export Changed. Má nastavení GPU formátů po mapách,
  export pokročilého terénního profilu a VTK shader pro parallax a POM.
  Renderer a jeho omezení jsou popsány v [rozhodnutích](DECISIONS.md).
- Blender podporuje nové profily, editaci parametrů, height-blend node tree,
  import/export, projektový round-trip a práci s GPU texturami. Dynamické ENUM
  položky a registrace mají regresní testy. Neznámá volitelná rozšíření na
  vybraných místech se uchovávají jako neprůhledná JSON data s varováním.
- Byl proveden audit dostupných consumerů a je zveřejněna
  [matice podpory](../adm-standard/IMPLEMENTATION_SUPPORT_MATRIX.md). Není
  vydávána za nezávislou certifikaci.

## Částečně dokončeno a odloženo

- Čtyřvrstvý primitiv neumí přesně vyjádřit pět současně aktivních povrchů;
  ořez může vytvořit švy. Referenční export hlásí 54 konfliktních trojúhelníků.
- Samostatná core-PBR BC5 normála nemá současně zachovanou primární BC5
  texturu a rekonstruovaný RGB fallback podle současného kontraktu.
- Blender zachovává parametry POM, ale nativně nevykresluje jeho UV posun.
  Ve vícevrstvém World Tile náhledu používá finální pohled při režimu
  parallaxu `NONE` CPU kompozici; per-fragment shader se používá při parallaxu,
  POM a shaderových diagnostikách.
- Neznámé neprůhledné reference nelze obecně přemapovat bez jejich schémat.
  Blender nezachovává všechna umístění rozšíření; World Tile neznámá shaderová
  nastavení uchová v AWTP, ale odmítne je exportovat.
- VTK shader hooks a BC7 dekódování byly ověřeny na Windows, nikoli plošně
  na ostatních platformách. Nezávislá implementace a všechny přípustné
  dependency resoluce nebyly ověřeny.
- Blender nadále hlásí dependency cycles. Hodnocení příčiny a dopadu vyžaduje
  další práci; varování nejsou potlačena.

Tato omezení nejsou všechna externí blokéry. Limit čtyř vrstev a BC5 fallback
jsou konflikty současného kontraktu; CPU preview a neúplné zachování dat jsou
nedokončená implementace. Neznámá schémata a nedostupné platformy omezují
nezávislé ověření.

## Distribuční balíčky

| Balíček | SHA-256 | Ověření |
|---|---|---|
| [Blender 1.24.45](../dist/adm_tools-1.24.45.zip) | `4621A21D92CAF052FF9289CE1D4F44EB686E9B8EAB0365842ED1C63F70A4F25C` | Integrita ZIP, 48 souborů shodných se zdrojem, bez vnořených ZIPů; extrahované regrese a izolovaná instalace a reaktivace prošly. |
| [World Tile 0.7.17](../dist/appartus-world-tile-0.7.17.zip) | `CF8E554091322C8C31ED2C46DA81F577DD9EB72215B102FD91C6FFC4707AA195` | Integrita ZIP, 102 souborů shodných se zdrojem; extrahované exportní regrese a přemístěný referenční projekt prošly. |

Starší Blender ZIPy 1.24.41 a 1.24.42 obsahují nechtěný lokální vnořený archiv
a nesmí se distribuovat. Během dřívějšího instalačního testu byl v uživatelském
repozitáři Blenderu nahrazen nainstalovaný ADM Tools verzí 1.24.43; původní verze
nebyla zaznamenána. Následný test 1.24.45 použil izolované nastavení i repozitář.

## Testy a měření

- Blender 5.2.3: 36 build kroků prošlo, 2 150 hlášených případů prošlo a
  10 externích případů bylo přeskočeno kvůli chybějícím souborům, oprávnění
  nebo cíli pro binding. Matice testovala 1.24.44 před změnou verze na 1.24.45.
  Extrahovaná 1.24.45 prošla cílenými testy. Původní ENUM a registrační chyby
  v build logu nebyly.
- World Tile: 131 testů prošlo na Windows s VTK 9.7.2. Extrahovaný balíček
  prošel pěti exportními regresemi a přemístěný projekt vytvořil čtyři
  validované dlaždice. Cross-application round-trip dlaždice z World Tile
  0.7.16 v Blenderu zachoval devět primárních BC4/BC5/R16 blobů byte-for-byte.
  Shader registry odpovídá 47 profilům;
  katalog referencí prošel kontrolou osmi kategorií.
- Na jednom Windows stroji měl náhled medián 110,2 ms po zahřátí; příprava
  referenční R16 textury 66,81 ms, detekce nezměněných dlaždic 7,50 ms,
  export jedné dlaždice 748,98 ms a čtyř dlaždic 790,70 ms. Špičkový pracovní
  set procesu byl 586 678 272 bajtů. Nejde o garance ani měření alokace GPU.

Podrobné postupy, varování a časování jsou v [TESTS.md](TESTS.md).

## Referenční výstupy

- [Přenosný AWTP projekt a textury](../appartus_world_tile/reference_project/)
  obsahuje čtyři dlaždice a tři LOD; [projekt](../appartus_world_tile/reference_project/advanced_reference.awtp)
  se přenáší s celou složkou.
- [Referenční ADM scéna](../appartus_world_tile/reference_project/advanced_material_reference.adm)
  má vizualizaci určenou pro tento fixture, nikoli obecný ADM renderer.
- [Render POM](../dist/advanced-reference-pom.png) a
  [render bez POM](../dist/advanced-reference-no-pom.png).
