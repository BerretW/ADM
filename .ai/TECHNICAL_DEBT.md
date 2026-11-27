# Technický dluh pro následující misi

Tento seznam popisuje přijatá omezení a nedokončenou implementaci. Doporučení
nejsou povolením rozšiřovat standard v již uzavřené misi.

## Více než čtyři materiálové vrstvy

- **Závažnost:** vysoká; ořez může způsobit viditelné švy na hranicích dlaždic
  a LOD.
- **Příčina:** primitiv má čtyři sloty `COLOR_1`; pět současně nenulových
  povrchů do nich nelze přesně uložit. Různé trojúhelníky mohou vybrat různé
  čtyři vrstvy.
- **Současný postup:** export vypisuje počet konfliktů. Omezte aktivní povrchy
  na čtyři v dotčené oblasti a zkontrolujte výstup v detailním náhledu.
- **Budoucí řešení:** navrhnout a otestovat konzistentní rozdělení palet
  a chování hranic; pokud je nutné přesně zobrazit pět vrstev současně,
  samostatně rozhodnout o kompatibilním kontraktu a jeho governance.

## Core-PBR BC5 fallback

- **Závažnost:** vysoká pro přenositelnost normálových map.
- **Příčina:** BC5 primární textura vyžaduje dvoukanálový fallback, zatímco
  samostatná core-PBR normála potřebuje rekonstruované RGB. Jedna textura
  podle současného kontraktu neumí vyjádřit oba požadavky.
- **Současný postup:** Blender zachová BC5 a varuje před zobrazením fallbacku.
  U vrstvených materiálů může samostatná shaderová reference držet BC5,
  zatímco core PBR používá rekonstruované RGB.
- **Budoucí řešení:** prověřit interoperabilní reprezentaci obou referencí a
  její náklady; případnou změnu kontraktu projednat samostatně.

## Nativní Blender POM preview

- **Závažnost:** střední; authoring je zachován, vizuální posouzení v Blenderu
  není ekvivalentní POM.
- **Příčina:** Blender preview node tree nevykonává POM ray marching ani
  odpovídající UV posuny. AO je v náhledu aproximováno.
- **Současný postup:** Blender zachovává POM parametry a omezení oznamuje.
  Skutečný POM lze ověřit ve World Tile VTK náhledu nebo referenční vizualizaci.
- **Budoucí řešení:** ověřit proveditelnost rozšiřitelného Blender rendereru
  a přidat obrazové testy proti referenční matematice bez vydávání bumpu za POM.

## Opaque extension reference remapping

- **Závažnost:** vysoká při úpravách a opětovném exportu neznámých rozšíření.
- **Příčina:** bez schématu nelze rozlišit indexy a reference od obyčejných
  hodnot ani je bezpečně přemapovat. Některá umístění rozšíření a neimportované
  uzly se obecně nezachovávají.
- **Současný postup:** Blender uchovává JSON na podporovaných místech, varuje
  a odmítá některé nejednoznačné transformace. World Tile neznámá shaderová
  nastavení uchovává v projektu, ale odmítne build a export.
- **Budoucí řešení:** zavést explicitní schématy a referenční mapování pro
  známá rozšíření; pro ostatní rozšířit bezztrátové uchování nebo odmítnutí
  tam, kde nelze zaručit bezpečný výstup.

## Multiplatformní ověření GPU kodeků

- **Závažnost:** vysoká pro vydání mimo ověřené prostředí.
- **Příčina:** Blender BC7 cesta používá nativní DDS dekodér; byla ověřena
  pouze na Windows a Blenderu 5.2.3. Úplná nezávislá KTX2 a GPU interoperabilita
  a všechny povolené dependency resoluce nejsou ověřeny.
- **Současný postup:** používat otestované Windows prostředí a PNG fallback;
  nepovažovat výsledky referenčních testů za nezávislou certifikaci.
- **Budoucí řešení:** spustit nezávislé vektory, načtení a GPU upload na Linuxu
  a macOS i dalších podporovaných verzích Blenderu/VTK; ověřit dependency
  graph a zaznamenat přesné platformy a dekodéry.

## Blender dependency-cycle warnings

- **Závažnost:** střední; testy prošly, ale příčina a dopad nejsou uzavřeny.
- **Příčina:** Blender při některých materiálových a scénových testech
  detekuje dependency cycles; konkrétní příčina každého cyklu nebyla prokázána.
- **Současný postup:** zachovat úplné diagnostické logy, testy spouštět
  samostatně s časovým limitem a varování nepotlačovat.
- **Budoucí řešení:** izolovat minimální scénu a node graph pro jednotlivé
  cykly, ověřit vliv na výsledek a výkon a opravit jejich skutečný původ.

## Vícevrstvý náhled bez parallaxu

- **Závažnost:** střední; finální náhled není v tomto režimu skutečnou
  per-fragment shaderovou implementací height blendingu.
- **Příčina:** při `parallax_mode = NONE` používá finální vícevrstvý pohled
  CPU kompozici. Shader se používá při parallaxu/POM a diagnostikách.
- **Současný postup:** použít detailní terénní shaderový náhled nebo shaderové
  diagnostiky a brát CPU kompozici a průměrné váhy jako aproximace.
- **Budoucí řešení:** použít existující vrstvený VTK shader také pro finální
  náhled bez parallaxu; ověřit reálné pixely, limity texturových jednotek,
  chybové stavy a výkon bez změny rychlých náhledových režimů.

## Další otevřené položky

- **Závažnost:** střední. Kompletní authoring a round-trip všech nepodporovaných
  parametrů zůstávají částečné; zachovat původní projekt a respektovat varování
  či odmítnutí exportu. Doplnit testy a podporu podle dostupných schémat.
- **Závažnost:** střední. Fixture-specific VTK vizualizace není obecný ADM
  renderer. Použít ji pouze pro přiloženou scénu; do budoucna ověřit výstup
  nezávislým rendererem.
- **Závažnost:** střední. Testovaný dependency graph není úplný lock všech
  přípustných verzí. Před distribucí dalších sestav ověřit konkrétní instalaci
  a podle potřeb projektu zavést reprodukovatelný dependency graph.
