# ADM – Advanced Material and Terrain Integration

## 0. Autonomous execution protocol
Pracuješ v existujícím repozitáři:

[https://github.com/BerretW/ADM](https://github.com/BerretW/ADM)

Referenční stav při sestavení zadání:

`19fc2a48a78dc876420334ba43109b1dcdbf30c1`

Pracuj nad aktuálním stavem workspace. Pokud mezitím přibyly další změny, zachovej je a přizpůsob jim implementaci.

Toto zadání představuje jednu kompletní vývojovou misi, nikoliv sérii samostatných úkolů vyžadujících potvrzení uživatele.

Před zahájením implementace:

- Ulož kompletní zadání do `.ai/MISSION.md`.
- Vytvoř `.ai/TASKS.md` se všemi požadavky.
- Vytvoř `.ai/STATE.md`.
- Vytvoř `.ai/DECISIONS.md`.
- Vytvoř `.ai/TESTS.md`.
- Respektuj existující projektové instrukce a Autonomous Development Protocol, pokud je již přítomen.
Po každé významné změně aktualizuj persistentní stav.

Po dokončení dílčího úkolu automaticky pokračuj dalším. Nečekej na potvrzení uživatele.

Pokud narazíš na překážku v jedné komponentě, zaznamenej ji a pokračuj v ostatních nezávislých úkolech.

Neukončuj práci po dokončení jednoho milestone.

Při ztrátě kontextu obnov stav z persistentních souborů.

Pokud některá část zadání již byla implementována, ověř ji, otestuj a integruj. Nevytvářej duplicitní implementaci.

## 1. Hlavní cíl
Kompletně rozšiř ADM formát, normativní specifikaci, shaderové profily a všechny nástroje pracující s materiály o:

- Per-layer Ambient Occlusion.
- Per-layer Heightmap.
- Height Based Blending.
- Parallax Mapping.
- Parallax Occlusion Mapping.
- GPU optimalizované jednokanálové textury.
- Pokročilé GPU formáty normal a albedo textur.
- Plnohodnotný material authoring.
- Funkční material preview.
- Import a export.
- Automatické testy.
- Referenční assety.
Prioritní součásti:

1. ADM Standard.
2. Existing material authoring tools: ADM Blender Plugin and Apparatus World Tile Editor.
3. Other existing tools that consume or author ADM materials and shaders.

The mission does not require creating a new standalone ADM Editor. If no standalone
editor exists in the repository, transfer every ADM Editor requirement to the
relevant existing authoring tools, especially the ADM Blender Plugin and
Apparatus World Tile Editor. Do not create a separate editor application.
4. ADM Blender Plugin.
5. Všechny ostatní shaderové komponenty repozitáře.
ADM musí zůstat nezávislým otevřeným standardem.

Nevytvářej žádnou závislost na RDR2, Raven Engine, Echo3D, Unity, Unreal Engine ani konkrétním grafickém API.

Vstupní materiálové textury jsou již rozdělené externím nástrojem. Přímá podpora RDR2 MA formátu není součástí zadání.

## 2. Respektování aktuálního stavu World Tile Editoru
Od původního návrhu byl World Tile Editor významně rozšířen.

Před implementací prostuduj změny mezi:

`9b16598ec4aa0aab48f5a8178e94b0b64210a730`

a

`19fc2a48a78dc876420334ba43109b1dcdbf30c1`

Zaměř se na:

- `appartus_world_tile/awt/material.py`
- `appartus_world_tile/awt/texturing.py`
- `appartus_world_tile/awt/project.py`
- `appartus_world_tile/awt/terrain_presets.py`
- `appartus_world_tile/awt/adm_export.py`
- `appartus_world_tile/awt/gui/main_window.py`
- `appartus_world_tile/awt/gui/material_panel.py`
- `appartus_world_tile/tests/test_export.py`
- `appartus_world_tile/tests/test_pipeline.py`
- `appartus_world_tile/tests/test_terrain_setup.py`
- `appartus_world_tile/tests/test_terrain_wizard.py`
Aktuální implementace obsahuje:

- Surface Library.
- Biome Surface Noise.
- World-space noise.
- Interaktivní biome height controls.
- Surface preview typu Sphere.
- Surface preview typu Plane.
- Surface preview typu Terrain Relief.
- Ovládání kamery.
- Texture Repeat v metrech.
- AWTP projektové verze 2, 3 a 4.
- Material presets včetně novější verze s noise.
- Vertex COLOR_1 blending.
- Terrain Four Layer shader 2.0.0.
- Road system.
- Biome painting.
- Surface painting.
- Texture refinement.
- Export Changed.
- RTIN terrain generation.
- Bezešvé LOD hranice.
Veškerou uvedenou funkcionalitu zachovej.

Neprováděj kompletní přepis World Tile Editoru.

Rozšiřuj současné třídy, datové struktury, workflow a testovací infrastrukturu.

## 3. GPU Texture Standard
Rozšiř ADM GPU texture registry o:

Formát | DXGI | Použití

R8_UNORM | 61 | Skalární mapy

R16_UNORM | 56 | Přesné heightmapy

BC4_UNORM | 80 | Komprimované skalární mapy

BC5_UNORM | 83 | Normal mapy

BC7_UNORM | 98 | Lineární textury

BC7_SRGB | 99 | Barevné textury
Zachovej podporu existujících GPU formátů.

Rozšiř DDS DX10 a KTX2.

Definuj normativně:

- Identifikátory formátů.
- Channel layout.
- Block dimensions.
- Block sizes.
- Mipmap byte sizes.
- Color space.
- Texture roles.
- Missing-channel behavior.
- Fallback semantics.
- Texture validation.
- Capability negotiation.
Rozšiř GPU texture capabilities v souladu s ADM governance.

Neměň potichu význam již existujících capability identifikátorů.

Aktualizuj zejména:

- `adm-standard/ADM-1.0-SPEC.md`
- GPU texture registry.
- Capability registry.
- `adm_blender/core/gputex.py`
- Core validators.
- Image decoders.
- Image encoders.
- Texture tests.
- Texture fixtures.
Využij existující BC3/BC4 block encoding infrastrukturu, pokud je vhodná.

Nevytvářej redundantní DDS a KTX2 implementace v každém nástroji.

Sdílej společnou implementaci, kde je to možné.

### 3.1 GPU optimalizované textury
Preferované formáty:

- Albedo: BC7_SRGB nebo kompatibilní BC1/BC3.
- Normal: BC5_UNORM.
- AO: BC4_UNORM.
- Roughness: BC4_UNORM.
- Metallic: BC4_UNORM.
- Height: R8_UNORM, R16_UNORM nebo BC4_UNORM.
- Emission: odpovídající barevný formát.
PNG zůstává kompatibilním fallbackem a authoring formátem.

PNG nesmí být preferováno před podporovanou GPU texturou při runtime načítání.

Podporované DDS a KTX2 textury zachovávej byte-for-byte, pokud již splňují požadavky standardu.

Zabraň zbytečné dekompresi a opakované kompresi.

### 3.2 Precision and mipmaps
Zachovej původní přesnost heightmap.

Nikdy automaticky nepřeváděj 16bitovou heightmap na 8bitovou.

R16 fallback musí zachovat 16bitovou přesnost.

Generuj korektní mipmapy nebo zachovávej validní existující mipmap chain.

Normal mapy filtruj ve vektorovém prostoru a normalizuj.

Definuj filtrování skalárních heightmap.

BC4 komprese nesmí být povinná pro heightmapy.

### 3.3 Normal maps
Pro BC5_UNORM používej rekonstrukci:

```
x = 2 * R - 1
y = 2 * G - 1
z = sqrt(max(0, 1 - x*x - y*y))

normal = normalize(vec3(x,y,z))
```
Zachovej ADM tangent-space +Y convention.

Definuj korektní RGB fallback.

## 4. ADM Material Height Extension
Vytvoř obecné verzované materiálové rozšíření umožňující definici povrchového reliéfu.

Navrhované označení:

`ADM_material_height_v1`

Konečný název přizpůsob existujícím ADM konvencím.

Rozšíření musí podporovat:

- Height texture.
- Channel selection.
- Inversion.
- Height scale.
- Height bias.
- Reference height.
- UV set.
- Parallax mode.
- Parallax scale.
- POM step settings.
Materiálová heightmap musí být použitelná i mimo terénní shader.

Jednoznačně rozlišuj:

1. Geometrickou heightmapu terénu.
2. Materiálovou heightmapu povrchu.
3. Případný budoucí geometric displacement.
Materiálová heightmap nesmí sama měnit geometrii, kolize, bounding boxes ani LOD geometrie.

Nevytvářej druhou konkurenční definici existujícího top-level `occlusionTexture`.

## 5. Nové verzované shaderové profily
Rozšiř následující profily:

- `adm.terrain.four_layer@1.1.0`
- `adm.terrain.four_layer@2.1.0`
- `adm.surface.two_layer@1.1.0`
- `adm.pbr.layered@2.1.0`
Pokud aktuální registry nebo governance vyžadují jiné verze, použij správné nové verze.

Zachovej původní profily 1.0.0 a 2.0.0.

Neměň jejich existující matematické chování.

Dodržuj freeze manifest a development change control.

Nové profily musí mít:

- Normativní dokumentaci.
- Shader registry entries.
- Default values.
- Parameter bounds.
- Texture roles.
- Capability requirements.
- PBR fallback.
- Reference pseudocode.
- Conformance fixtures.
- Automated tests.
Terrain Four Layer 2.x s COLOR_1 je prioritní.

Zachovej zároveň variantu s texture-based blend mask.

## 6. Per-layer Ambient Occlusion
Pro každou vrstvu přidej:

```
layer{i}_ao_texture
layer{i}_ao_channel
layer{i}_ao_invert
layer{i}_ao_strength
```
Výchozí nastavení:

```
texture = null
channel = R
invert = false
strength = 1.0
```
Matematický kontrakt:

```
sample = sample_selected_linear_channel(texture)

if invert:
    sample = 1 - sample

ao = mix(1.0, sample, strength)
```
Chybějící AO textura:

```
ao = 1.0
```
Výsledné AO:

```
finalAO = sum(finalWeight[i] * layerAO[i])
```
Definuj kombinaci s top-level AO.

AO aplikuj na nepřímou difuzní složku osvětlení.

AO nesmí automaticky ztmavovat veškeré přímé osvětlení, emission ani samotné albedo.

Pokud preview backend nedokáže oddělit nepřímé osvětlení, použij transparentně dokumentovanou aproximaci.

## 7. Per-layer Heightmap
Pro každou vrstvu přidej:

```
layer{i}_height_texture
layer{i}_height_channel
layer{i}_height_invert
layer{i}_height_scale
layer{i}_height_bias
layer{i}_parallax_scale
```
Výchozí nastavení:

```
texture = null
channel = R
invert = false
scale = 1.0
bias = 0.0
parallax_scale = 0.0
```
Konvence:

- 0 = nejnižší část povrchu.
- 1 = nejvyšší část povrchu.
- Lineární data.
- Žádná gamma korekce.
Normativně definuj efektivní výšku, bounds, clipping a missing-texture behavior.

Různé materiálové mapy mohou mít rozdílná rozlišení.

Nepřevzorkovávej automaticky všechny textury na jednotnou velikost.

## 8. Height Based Blending
Přidej parametry:

```
height_blend_enabled
height_blend_transition
height_blend_strength
```
Výchozí nastavení:

```
enabled = false
transition = 0.2
strength = 1.0
```
Výchozí algoritmus pro posouzení:

```
w = normalized_base_weights

h_max = max(height[i] for active layers)

q[i] = w[i] * exp(
    clamp(
        (height[i] - h_max) / max(transition, epsilon),
        -80,
        0
    )
)

height_weights = normalize(q)

final_weights = mix(
    w,
    height_weights,
    height_blend_strength
)
```
Před přijetím algoritmu ověř jeho vizuální a numerické chování.

Pokud zvolíš jiný algoritmus, musí splňovat stejné invarianty a být přesně specifikován.

Povinné invarianty:

- Součet výsledných vah je 1.
- Váhy jsou nezáporné.
- Nulová původní váha zůstane nulová.
- One-hot masky zůstávají one-hot.
- Stejné efektivní výšky nemění původní váhy.
- Chybějící heightmapy mají definované neutrální chování.
- Materiály bez heightmap používají původní blending.
- Vypnutý efekt reprodukuje starší shader.
- Strength 0 reprodukuje starší shader.
- Výsledek nezávisí na pořadí vrstev.
- Výsledek neobsahuje NaN nebo Inf.
Výsledné váhy použij konzistentně pro:

- Albedo.
- Alpha.
- Normal.
- Metallic.
- Roughness.
- AO.
- Emission.
Normalizuj výslednou normal map.

## 9. Integrace Surface Noise a Height Based Blending
Toto je zásadní aktualizace proti původnímu zadání.

Aktuální World Tile Editor již obsahuje Surface Noise v biome pravidlech.

Neodstraňuj tento systém ani jej nenahrazuj height blendingem.

Zachovej existující generování makroskopických vah, včetně:

- Height bands.
- Slope bands.
- Biome transitions.
- Surface Noise.
- Biome painting.
- Surface painting.
- Roads.
- Texture refinement.
Použij následující oddělení odpovědnosti:

### Authoring a geometrická fáze

```
Biome rules
    ↓
Surface Noise
    ↓
Biome and surface painting
    ↓
Road overrides
    ↓
Surface weights
    ↓
COLOR_1
```
Přesné pořadí existujících operací zachovej podle současné implementace.

### Shaderová fáze

```
COLOR_1
    ↓
Base layer weights
    ↓
Optional parallax evaluation
    ↓
Material height sampling
    ↓
Height Based Blending
    ↓
Final material properties
    ↓
PBR lighting and AO
```
Surface Noise řeší makroskopické rozmístění povrchů.

Height Based Blending řeší mikroskopické prolínání materiálů.

Parallax řeší optický povrchový reliéf.

Nesnaž se všechny tři technologie spojit do jediného efektu.

Neměň obsah COLOR_1 na základě height textury při exportu.

Nevypaluj Height Based Blending do vertex weights.

Height blending musí zůstat skutečným shaderovým efektem.

## 10. Parallax a POM
Implementuj volitelné režimy:

```
NONE
PARALLAX
PARALLAX_OCCLUSION
```
Výchozí režim je NONE.

Přidej:

```
parallax_mode
parallax_min_steps
parallax_max_steps
layer{i}_parallax_scale
```
Normativně definuj:

- Tangent-space view direction.
- Reference height.
- Scale units.
- UV displacement direction.
- Grazing-angle behavior.
- Adaptive step count.
- Ray intersection.
- Intersection refinement.
- UV wrapping.
- Sampling and mip selection.
- Missing heightmap behavior.
- Missing tangent behavior.
- Frontface and backface behavior.
- Multiple layer interaction.
Jednoznačně definuj, zda a jak se při ray marchingu mění váhy jednotlivých vrstev.

Nesmí vzniknout cyklická nebo nejednoznačná závislost mezi POM a Height Based Blending.

Všechny materiálové mapy dané vrstvy musí být vzorkovány konzistentně.

Pokud používají rozdílné UV sady, definuj transformaci nebo podporovaná omezení.

POM je optický efekt, nikoliv geometrický displacement.

POM nesmí být povinné pro každý materiál.

Neprezentuj Bump Mapping jako plnohodnotné POM.

## 11. ADM Editor Integration
Najdi aktuální implementaci ADM Editoru a všech dalších authoring nástrojů.

Rozšiř existující material editor.

Každá vrstva musí obsahovat:

```
Layer
 ├─ Albedo
 ├─ Normal
 ├─ Metallic
 ├─ Roughness
 ├─ Ambient Occlusion
 ├─ Height
 ├─ Emission
 ├─ UV settings
 └─ Parallax settings
```
Přidej:

- Texture selection.
- Channel selection.
- Inversion.
- Texture preview.
- AO strength.
- Height scale.
- Height bias.
- Height blend settings.
- Parallax settings.
- GPU format selection.
- Shader version selection.
- Material validation.
Zobrazuj informace o textuře:

- Rozlišení.
- Skutečný GPU formát.
- Bitová hloubka.
- Color space.
- Mipmap count.
- GPU memory estimate.
- External/embedded status.
Použij registry-driven UI, pokud to stávající architektura umožňuje.

Nevytvářej ručně udržovanou duplicitní shader registry.

### Preview
Zajisti funkční preview nových shaderů.

Režimy:

- Final Material.
- Albedo.
- Normal.
- AO.
- Roughness.
- Metallic.
- Height.
- Base Layer Weights.
- Height Blended Weights.
- Parallax Offset.
- COLOR_0.
- COLOR_1.
Přidej přepínání klasického a výškového prolínání.

Zachovej editaci starších shaderových verzí.

Upgrade materiálu na novou shaderovou verzi musí být explicitní nebo provedený při použití nové funkce s jasným oznámením.

Neprováděj tichou destruktivní migraci.

## 12. World Tile Editor – datový model
Rozšiř existující třídy v `awt/material.py`.

Především:

- `MapSlot`
- `Surface`
- `Biome`
- `TerrainMaterial`
Pro AO a Height znovu využij `MapSlot`, pokud jeho současný kontrakt umožňuje příslušnou texturovou referenci, channel selection a inversion.

Nevytvářej druhý konkurenční systém map slotů.

Rozšiř `Surface` o:

- AO map.
- AO strength.
- Height map.
- Height scale.
- Height bias.
- Parallax scale.
- Emission, pokud dosud není součástí struktury.
Rozšiř `TerrainMaterial` nebo odpovídající shader settings o:

- Height blending enable.
- Height blend transition.
- Height blend strength.
- Parallax mode.
- POM settings.
- Target shader version.
Rozšiř všechny související operace:

- `Surface.textures()`
- `TerrainMaterial.textures()`
- `_surface_dict()`
- `TerrainMaterial.to_dict()`
- `TerrainMaterial.from_dict()`
- `TerrainMaterial.validate()`
- `TerrainMaterial.fingerprint()`
- Material presets.
- Relative texture paths.
- Texture collection.
- Project serialization.
Důsledně rozlišuj:

- Geometrické a biome rule změny.
- Čistě materiálové změny.
Změna AO nebo height textury nesmí vyžadovat rebuild geometrie.

`rules_digest()` nesmí být zbytečně ovlivňován čistě shaderovými parametry.

Material fingerprint naopak musí zahrnovat všechny nové shaderové vlastnosti a jejich textury.

## 13. World Tile Editor – GUI
Rozšiř `awt/gui/material_panel.py`.

Využij existující třídy:

- `TexturePicker`
- `MapRow`
- `SurfaceEditor`
- `MaterialPreview`
- `MaterialPanel`
Zachovej jejich stávající funkcionalitu.

Přidej AO a Height do existujícího Surface Editoru.

Rozšiř MapRow nebo vytvoř jeho kompatibilní specializaci pro potřebné parametry.

Přidej sekci Terrain Shader Settings.

Uživatel musí mít možnost nastavit:

- AO map.
- AO strength.
- AO channel.
- AO invert.
- Height map.
- Height channel.
- Height invert.
- Height scale.
- Height bias.
- Height Blend Strength.
- Height Blend Transition.
- Parallax Mode.
- Parallax Scale.
- POM steps.
Zachovej:

- Biome Editor.
- Surface Noise slider.
- Interaktivní biome controls.
- Surface naming.
- Texture repeat in metres.
- Stávající signály a editovací workflow.
Nepřepisuj kompletní uživatelské rozhraní.

## 14. World Tile Editor – Material Preview
Toto je prioritní část.

Aktuální MaterialPreview podporuje:

- Sphere.
- Plane.
- Terrain Relief.
- Rotation.
- Pan.
- Zoom.
- Texture repeat.
Zachovej všechny uvedené funkce.

Aktuální preview podle dokumentace zobrazuje albedo, tint a skalární Metallic/Roughness, ale nezobrazuje všechny skutečné materiálové mapy.

Rozšiř jej na skutečný material preview.

Musí zobrazovat:

- Albedo textures.
- Normal maps.
- Metallic maps.
- Roughness maps.
- AO maps.
- Height maps.
- Parallax.
- POM podle deklarované podpory.
Zachovej fyzické rozměry a texture repeat convention současného preview.

Jednovrstvá Sphere nebo Plane preview nesmí předstírat funkčnost Height Based Blending mezi vrstvami.

Pro testování Height Based Blending vytvoř samostatný multi-surface preview režim, který umožňuje:

- Vybrat dva až čtyři povrchy.
- Nastavit základní blend weights.
- Zobrazit klasické prolínání.
- Zapnout Height Based Blending.
- Měnit transition a strength.
- Zobrazovat finální váhy.
- Měnit světlo a kameru.
Rozšiř také:

- Show blended terrain.
- Selected tile preview.
- 3D terrain Material mode.
Pro rozsáhlý terén zachovej rychlé preview režimy.

Detailní materiálový preview nesmí být povinný při prohlížení geometrie, LOD nebo biome weights.

Pokud současný renderer nezvládá nové efekty, rozšiř vhodně jeho materiálovou pipeline.

Nevytvářej paralelní náhledový systém bez nutnosti.

## 15. World Tile Editor – Import Texture Sets
Přidej funkci Import Material Sets from Directory.

Uživatel již má samostatné rozdělené DDS textury uložené vedle sebe.

Například:

```
rock_01_abte.dds
rock_01_nm.dds
rock_01_ma.dds
rock_01_ao.dds
rock_01_roughness.dds
rock_01_height.dds
rock_01_unknown.dds
```
Výsledkem musí být jeden povrch `rock_01`.

Rozpoznávej konfigurovatelné přípony:

```
_abte
_albedo
_basecolor
_diffuse
_nm
_normal
_ao
_occlusion
_roughness
_metallic
_height
_displacement
_emission
_emissive
```
Podporuj DDS, KTX2, PNG, TIFF a TGA jako authoring vstupy.

Soubor `_ma` automaticky ignoruj, pokud jsou již přítomny rozdělené mapy.

Soubor `_unknown` nikdy automaticky nepřiřazuj ke konkrétní materiálové vlastnosti.

Funkce musí umožnit:

- Rekurzivní prohledání adresáře.
- Seskupení materiálů.
- Náhled nalezených sad.
- Kontrolu chybějících map.
- Řešení konfliktních variant.
- Volbu jednotlivých povrchů k importu.
- Zachování existujících povrchů.
- Volitelnou aktualizaci existujících povrchů.
Heuristiky názvů jsou pouze authoring pomůcka.

Výsledný ADM materiál musí obsahovat explicitní texture references.

Nesmí být závislý na příponách souborů.

## 16. World Tile Editor – Project and Presets
Aktuální `PROJECT_VERSION = 4`.

Stávající implementace zapisuje projektovou verzi 4 při použití Surface Noise, jinak zachovává verzi 3.

Zachovej tento princip kompatibility, pokud je to vhodné.

Při zavedení nových materiálových vlastností definuj novou projektovou verzi, například AWTP 5.

Požadavky:

- AWTP 2 lze načíst.
- AWTP 3 lze načíst.
- AWTP 4 lze načíst.
- Nová verze zachovává všechny nové vlastnosti.
- Staré projekty používají neutrální výchozí hodnoty.
- Surface Noise zůstává zachováno.
- Roads zůstávají zachovány.
- Paint data zůstávají zachována.
- Relative paths zůstávají zachovány.
Při uložení staršího projektu nepřidávej nekompatibilní data pod historickým číslem verze.

Aktualizuj:

- `awt/project.py`
- `awt/terrain_presets.py`
- Material preset format.
- Terrain setup wizard.
- CLI.
- Manifest serialization.
- Project migration.
- Project validation.
Preset musí zachovat AO a Height textury včetně jejich relativních cest a všech parametrů.

Terrain Setup Wizard musí respektovat nově importované povrchy.

Zachovej nové biome graph ovládání z aktuálního `main_window.py`.

## 17. World Tile Editor – ADM Export Integration
Rozšiř `awt/adm_export.py`.

Zaměř se na:

- `ExportSettings`
- `prepare_adm_texture()`
- `material_key()`
- `tile_digest()`
- `changed_tiles()`
- `_surface_texture_slots()`
- `_material_params()`
- `build_tile_document()`
- `tile_geometry()`
Rozšiř exportní materiálové sloty o AO, Height a případné další nové mapy.

Nový shaderový profil musí být skutečně exportován.

Pouhé přidání vlastností do `.awtp` nestačí.

Přidej:

- Legacy Terrain 2.0.0 export.
- Advanced Terrain export.
- Explicitní target shader version.
- Automatickou volbu nové verze při použití nové funkcionality, pokud uživatel tuto možnost zapne.
Pokud cílový profil nepodporuje některý parametr, nikdy jej tiše neodstraňuj.

Informuj uživatele o ztrátě funkcionality nebo odmítni nekompatibilní export podle zvoleného režimu.

Zachovej:

- Embedded images.
- External images.
- Content hashing.
- Texture deduplication.
- Atomic writes.
- Validation.
- Shared texture folders.
- Export Changed.

### Tangents
Aktuální export generuje tangenty pouze tehdy, pokud některý použitý povrch obsahuje normal mapu.

Rozšiř podmínku také na height/parallax funkce, které vyžadují tangent frame.

Materiál s POM musí mít validní tangent-space frame i bez normal mapy.

Ověř winding, normal orientation a tangent handedness.

## 18. Seamless Terrain and LOD
Zachovej stávající RTIN geometrický systém.

Neměň jeho garantovanou maximální chybu.

Zachovej:

- Shared tile edges.
- World-space positions.
- LOD boundaries.
- Vertex COLOR_1.
- Biome weights.
- Surface Noise continuity.
- Road continuity.
- Texture repeat.
Aktuální export rozděluje triangles do primitives, které obsahují maximálně čtyři povrchy.

Prozkoumej:

- `triangle_masks()`
- `group_masks()`
- `_slots()`
- `color1()`
Height blending nesmí záviset na lokálním pořadí slotů.

Ověř shodu výsledného materiálu v situacích:

- Povrch má jiný lokální slot v sousední primitive.
- Sousední dlaždice mají odlišné surface sets.
- Sousední dlaždice používají různé LOD.
- Krajní dlaždice mají odlišné rozměry.
- Surface Noise zasahuje přes hranici dlaždic.
- Přechod biomet používá sdílené povrchy.
- Přechod biomet nemá žádný sdílený povrch.
- Na hranici jsou více než čtyři relevantní povrchy.
Prověř zejména UV phase u nepravidelně velkých krajních dlaždic. Nestačí předpokládat, že zaokrouhlení texture repeat automaticky zaručuje všechny potřebné vlastnosti.

Pokud jsou některá omezení přítomná již ve starší implementaci, zdokumentuj je a podle možností oprav.

Neporušuj geometrii kvůli opravě materiálového efektu.

## 19. Export Changed and Performance
Rozšiř fingerprinting tak, aby změna následujících hodnot označila pouze příslušné dlaždice jako změněné:

- AO image content.
- AO strength.
- AO channel.
- AO invert.
- Height image content.
- Height scale.
- Height bias.
- Height channel.
- Height invert.
- Height blend settings.
- Parallax settings.
- Shader version.
- GPU format configuration.
Při změně samotného materiálu nevyžaduj přepočet RTIN geometrie ani vertex weights.

Pokud současný fingerprint systém označuje všechny dlaždice jako změněné při úpravě nepoužitého povrchu, rozšiř jej o správnou závislost na použitých materiálech.

Zachovej cache a sdílení textur.

Měř výkon:

- Material preview.
- Texture preparation.
- Export Changed detection.
- Export jednoho tile.
- Export více tiles.
- CPU memory.
- GPU memory estimates.
Neporovnávej nesrovnatelné pracovní zátěže.

## 20. Blender Integration
Kompletně rozšiř `adm_blender`.

Aktualizuj:

- Core constants.
- Shader registry loading.
- Material properties.
- UI panels.
- Shader parameter groups.
- Shader node generation.
- Shader mathematics.
- Import.
- Export.
- Validation.
- Material conversion.
- Texture codecs.
- Vertex painting.
- GPU texture preservation.
Implementuj nové shaderové profily pomocí funkčních Blender node groups.

Sdílej matematiku a node groups tam, kde je to vhodné.

Zachovej existující COLOR_0 a COLOR_1 kontrakty.

Height Based Blending musí být skutečnou funkcí node tree.

Používej Non-Color pro všechny datové textury.

Zachovej heightmap bit depth.

Pokud Blender preview nepodporuje plnou POM implementaci, nesmí z tohoto důvodu odstraňovat POM parametry při import/export round-trip.

Transparentně označ preview approximations.

Aktualizuj všechny stávající shader-aware vertex painting nástroje.

## 21. Ostatní komponenty repozitáře
Proveď repository-wide audit všech shader consumers.

Zahrň:

- ADM Editor.
- Web editors.
- Viewers.
- Material inspectors.
- CLI.
- Importers.
- Exporters.
- Validators.
- Reference renderers.
- SDK.
- Fixture generators.
- Documentation generators.
Nevynechávej komponentu pouze proto, že nebyla uvedena explicitně v zadání.

Pro každou nalezenou komponentu stanov:

- Full support.
- Partial support.
- Fallback support.
- Not applicable.
Každé omezení zdokumentuj.

Nepodporované vlastnosti nesmí být tiše ztraceny při editaci a opětovném exportu.

Neslibuj plnou podporu shaderu, pokud implementace zobrazuje pouze PBR fallback.

## 22. Registry-driven Architecture
Shader registry a normativní dokumentace jsou autoritativní.

Nedovol vznik nezávislých verzí shaderových parametrů v jednotlivých nástrojích.

Sdílej:

- Parameter definitions.
- Parameter types.
- Default values.
- Bounds.
- Texture roles.
- Shader versions.
- Capabilities.
- UI metadata.
Pokud některý nástroj vyžaduje lokální generovanou registry, zajisti její deterministické generování a CI kontrolu.

Referenční matematika musí být nezávislá na konkrétním rendereru.

## 23. Automatické testování
Zachovej všechny existující testy.

Především nové testy Surface Noise, Terrain Wizard, Terrain Setup, Export a Pipeline.

Přidej následující skupiny.

### GPU Texture Tests

- R8 DDS a KTX2.
- R16 DDS a KTX2.
- BC4 DDS a KTX2.
- BC5 DDS a KTX2.
- BC7 DDS a KTX2.
- Odd texture dimensions.
- Malé mip levels.
- Neplatné hlavičky.
- Neplatné mip chains.
- Color space validation.
- External images.
- Embedded images.
- Fallback.
- R16 precision.
- GPU passthrough.
Použij nezávislé test vectors nebo ověřené dekodéry.

Netestuj vlastní enkodér pouze vlastním dekodérem.

### Shader Mathematics Tests

- Layer AO.
- Height scale/bias.
- Channel selection.
- Inversion.
- Missing maps.
- One-hot masks.
- Zero masks.
- Equal heights.
- Zero-weight layers.
- Layer permutation invariance.
- Disabled height blending.
- POM.
- Numerical stability.
- Backward compatibility.

### World Tile Tests

- AWTP 2/3/4 migration.
- Nový AWTP round-trip.
- Material presets round-trip.
- Surface Noise regression.
- Surface Noise + Height Based Blending.
- Roads regression.
- Biome painting regression.
- Surface painting regression.
- Import Material Sets.
- Missing texture maps.
- Duplicate names.
- AO/Height export.
- Texture passthrough.
- Tangents with POM without normal map.
- Export Changed.
- Different local layer slots.
- Tile boundaries.
- Different LOD.
- Non-uniform edge tiles.
- More than four surfaces.
- Geometry error guarantee.
- Material-only editing without rebuild.

### GUI Tests
Rozšiř existující GUI testovací infrastrukturu.

Testuj:

- Surface Editor.
- AO map selection.
- Height map selection.
- Shader settings.
- Surface Noise controls.
- Material import dialog.
- Preset save/load.
- Sphere preview.
- Plane preview.
- Terrain relief preview.
- Multi-surface preview.
- Project save/load.
- Export workflow.
Nestačí testovat existenci widgetu.

Ověř propojení UI, datového modelu, preview a exportu.

### Blender Tests

- Shader creation.
- Node generation.
- Import/export round-trip.
- Channel selection.
- AO.
- Height blending.
- COLOR_1 painting.
- BC4/BC5/BC7 texture handling.
- R16 precision.
- Old profile regression.
- External images.
- PBR fallback.
Přidej skutečný bake nebo render test, který ověří Height Based Blending.

## 24. Referenční projekty a assety
Vytvoř vlastní procedurální textury bez závislosti na cizích herních assetech.

Přidej referenční materiály:

- Rock.
- Sand.
- Dirt.
- Grass.
- Cobblestone.
Každý materiál musí obsahovat:

- Albedo.
- Normal.
- Roughness.
- AO.
- Height.
Vytvoř:

### ADM Advanced Terrain Test Scene
Ukazuje:

- Klasické prolínání.
- Height Based Blending.
- Layer AO.
- Parallax.
- POM.
- R8 Height.
- R16 Height.
- BC4 Height.
- BC5 Normal.
- BC7 Albedo.

### Advanced World Tile Test Project
Funkční `.awtp` projekt obsahující:

- Více sousedních tiles.
- Minimálně tři LOD.
- Několik biomů.
- Surface Noise.
- Height Based Blending.
- AO.
- Roads.
- Sdílené povrchy.
- Více než čtyři povrchy na úrovni světa.
Uživatel musí být schopen projekt otevřít, zobrazit, upravit materiály a exportovat ADM bez dodatečné přípravy.

Přidej assety do fixture katalogu.

Nevkládej do Git repozitáře nepotřebné velké binární soubory, cizí herní assety ani lokální cache.

## 25. Dokumentace
Aktualizuj:

- ADM Specification.
- Shader Registry.
- Extension Registry.
- Capability Registry.
- Texture Specification.
- Shader Profile Documentation.
- Changelog.
- README.
- ADM Editor documentation.
- World Tile Editor documentation.
- Blender Plugin documentation.
- SPEC_GAPS.
- Conformance documentation.
- Fixture catalog.
Přidej kapitolu vysvětlující rozdíl mezi:

- Surface Noise.
- COLOR_1 blending.
- Height Based Blending.
- Parallax.
- POM.
- Geometric terrain heightmap.
Přidej dokumentaci pro nezávislé engine implementátory.

Definuj přesné algoritmy, nikoliv pouze očekávaný vizuální vzhled.

Dokumentace musí odpovídat skutečně implementovaným funkcím.

## 26. Implementation Milestones

### M1 – Audit and persistent state
Prozkoumej aktuální repository.

Vytvoř kompletní checklist a identifikuj již existující funkcionalitu.

### M2 – GPU formats
Rozšiř standard, codecs, validation a testy.

### M3 – Material and shader contracts
Implementuj material height extension, AO, Height Based Blending, Parallax a POM contracts.

### M4 – Shared reference implementation
Implementuj společnou matematiku, registry integration a referenční testy.

### M5 – World Tile data model
Rozšiř Surface, MapSlot, TerrainMaterial, project format, presets a fingerprinting.

### M6 – World Tile GUI and Preview
Integruj nové mapy, shader settings, multi-surface preview a Material Set Import.

Zachovej všechny nově přidané uživatelské funkce.

### M7 – World Tile Export
Integruj nové shaderové profily, GPU textury, tangents, Export Changed a seam tests.

### M8 – ADM Editor
Kompletní material authoring, preview a serialization.

### M9 – Blender Plugin
Shader nodes, material editing, import/export a round-trip.

### M10 – Remaining ecosystem
Aktualizuj všechny další nalezené shader consumers.

### M11 – Fixtures and documentation
Vytvoř referenční ADM assety a funkční AWTP projekt.

### M12 – Full verification
Spusť kompletní dostupné testy, CI ekvivalenty a build procesy.

Oprav všechny zjištěné regresní chyby.

Po každém milestone automaticky pokračuj dalším.

Milestones slouží jako interní organizační struktura, nikoliv jako body vyžadující potvrzení uživatele.

## 27. Definition of Done
Mise je dokončena pouze tehdy, pokud:

- ADM standard normativně definuje nové funkce.
- GPU formáty mají funkční implementaci.
- Staré shadery fungují beze změny.
- Nové shaderové profily jsou v registry.
- AO funguje samostatně pro každou vrstvu.
- Height Based Blending funguje skutečně ve shaderu.
- Parallax a POM odpovídají deklarovaným kontraktům.
- ADM Editor umožňuje nové funkce vytvářet a editovat.
- World Tile Editor používá nové funkce v preview.
- World Tile Editor exportuje nové funkce do ADM.
- Surface Noise zůstává plně funkční.
- Nové preview zachovává Sphere, Plane a Terrain Relief.
- Starší AWTP projekty fungují.
- Material presets fungují.
- Roads a painting fungují.
- Export Changed funguje.
- Geometrické a LOD garance zůstávají zachovány.
- Blender plugin podporuje nové funkce a round-trip.
- Další shader consumers jsou aktualizovány.
- Referenční assety existují.
- Referenční AWTP projekt funguje.
- Dokumentace odpovídá implementaci.
- Testy prošly nebo jsou skutečné externí blokery explicitně doložené.
Nepoužívej placeholder implementations.

Nenechávej nefunkční UI prvky.

Nevynechávej požadavky kvůli velikosti zadání.

Nesnižuj kvalitu testů kvůli zelenému CI.

Neoznačuj úkol za dokončený pouze na základě úspěšné kompilace.

## 28. Completion audit
Před ukončením práce znovu načti `.ai/MISSION.md`.

Proveď audit každého požadavku proti `.ai/TASKS.md`.

Zkontroluj skutečnou implementaci, nikoliv pouze checklist.

Spusť kompletní dostupnou testovací sadu.

Pokud zůstává jakýkoliv splnitelný požadavek nedokončený, pokračuj v implementaci.

Závěrečný report musí obsahovat:

- Seznam upravených komponent.
- Nové shaderové profily.
- Nové GPU formáty.
- Změny ADM standardu.
- Změny World Tile Editoru.
- Změny ADM Editoru.
- Změny Blender pluginu.
- Zachované existující funkce.
- Skutečné výsledky testů.
- Výkonnostní měření, pokud byla provedena.
- Cesty k referenčním assetům.
- Cestu k referenčnímu AWTP projektu.
- Screenshoty nebo rendery funkčních výsledků.
- Zbývající omezení.
- Skutečné externí blokery.
Nezastavuj se u návrhu architektury.

Nezastavuj se po jednotlivém milestone.

Proveď kompletní implementaci celé mise.