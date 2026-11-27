# ADM – Advanced Terrain & Physical Surface System

# 1. Mission objective
Rozšiř existující ADM standard a jeho ekosystém o kompletní systém pokročilého terénního texturování, materiálového reliéfu a sémantických fyzikálních povrchů.

Cílem je umožnit vytváření vizuálně přesvědčivých terénů vhodných pro rozsáhlé otevřené světy a zároveň poskytnout enginům jednoznačná data o fyzikálních vlastnostech povrchu.

Moderní open-world hry, zejména Red Dead Redemption 2, představují pouze vizuální a technologickou inspiraci.

Nekopíruj proprietární shadery, algoritmy, datové formáty ani assety Rockstaru.

ADM musí zůstat:

- Otevřeným standardem.
- Nezávislým na konkrétním enginu.
- Datově řízeným.
- Deterministickým v normativně definovaných operacích.
- Zpětně kompatibilním.
- Použitelným pro real-time rendering.
- Použitelným na desktopových i konzolových platformách.
- Rozšiřitelným bez opakovaného přepisování existujících subsystémů.
ADM popisuje assety, jejich vzhled, geometrii, fyzikální povrchy a vlastnosti.

Engine rozhoduje o jejich využití.

---

# 2. Autonomous execution and persistent memory
Pracuj autonomně až do dokončení celé mise.

Nezastavuj se po jednotlivých milnících.

Nevyžaduj potvrzení běžných implementačních rozhodnutí.

Výchozí referenční stav posledního externího auditu:

- Repository: BerretW/ADM.
- Commit: `cd3c9b9d1bfe1e0a0d7f8a1718a899f0371b0969`.
- Blender Plugin: 1.24.45.
- World Tile Editor: 0.7.17.
- World Tile: 131 passing tests.
- Blender build: 36 passing steps.
- 2150 reported passing cases.
- 10 documented external-asset skips.
Tento commit představuje referenci, nikoliv požadavek na reset workspace.

Respektuj všechny novější změny.

Na začátku:

1. Prozkoumej aktuální stav repozitáře.
2. Načti existující `.ai/MISSION.md`.
3. Načti `.ai/FINAL_REPORT.md`, pokud existuje.
4. Načti `.ai/TECHNICAL_DEBT.md`, pokud existuje.
5. Načti TASKS, STATE, DECISIONS a TESTS předchozí mise.
6. Archivuj předchozí misi bez ztráty její historie.
7. Zaznamenej aktuální výchozí commit.
8. Ověř skutečný stav nezbytných závislostí.
9. Vytvoř persistentní dokumentaci nové mise.
Používej:

- `.ai/MISSION.md`
- `.ai/TASKS.md`
- `.ai/STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TESTS.md`
MISSION.md musí obsahovat kompletní toto zadání.

Neměň původní požadavky bez zaznamenání důvodu.

Průběžně zaznamenávej:

- Dokončenou práci.
- Otevřené požadavky.
- Technická rozhodnutí.
- Výsledky testů.
- Nalezené chyby.
- Skutečné blokery.
- Další konkrétní implementační kroky.
Při obnovení kontextu načti persistentní dokumentaci a pokračuj.

Dlouhotrvající externí procesy spouštěj s odpovídajícími časovými limity a průběžným logováním.

Neopakuj neúspěšné testy bez změny implementace nebo diagnostiky.

---

# 3. Existing implementation and compatibility
Využij existující implementace:

- ADM Core.
- Shader Registry.
- Capability Registry.
- Shader versioning and historical freezes.
- PBR materials.
- Layered material profiles.
- COLOR_0 and COLOR_1.
- Material Height Extension.
- Per-layer AO.
- Height Based Blending.
- Parallax Mapping.
- Parallax Occlusion Mapping.
- R8/R16 GPU textures.
- BC4/BC5/BC7 GPU textures.
- DDS and KTX2.
- Per-map GPU encoding.
- Source-byte preservation.
- Physical materials.
- Collider descriptors.
- RTIN terrain generation.
- Independent terrain tiles and LOD.
- Biomes.
- Surface Noise.
- Roads.
- Surface Library.
- Material presets.
- AWTP persistence.
- Export Changed.
- World Tile custom VTK shaders.
- Blender import/export.
- Unknown extension preservation.
Nevytvářej paralelní náhrady funkčních subsystémů.

Neprováděj rozsáhlé refaktory bez konkrétního technického důvodu.

Neměň význam existujících zmrazených shaderových profilů.

Zachovej současnou funkcionalitu a uživatelské workflow.

---

# 4. Mission architecture
Mise obsahuje čtyři související technologické oblasti.

## A. Advanced Terrain Texturing

- Terrain Control Maps.
- Seam-safe material palettes.
- Macro Color Mapping.
- Macro Normal Mapping.
- Anti-tiling.
- Stochastic Texture Sampling.
- Triplanar Mapping.
- Detail Material Maps.
- Per-layer material controls.
- Material Distance LOD.

## B. Advanced Material Relief

- Parallax Self-shadowing.
- True Displacement Mapping.
- Konzistentní kombinování materiálových efektů.
- GPU texture and sampling optimization.

## C. Physical Surface System

- Sémantické fyzikální materiály.
- Standardizované typy povrchů.
- Uživatelské podtypy.
- Semantic tags.
- Per-triangle collider materials.
- Independent terrain collision generation.

## D. Authoring and ecosystem integration

- World Tile Editor.
- Blender plugin.
- Validators.
- SDK.
- CLI.
- Existing viewers and reference renderers.
- Importers and exporters.
- Documentation.
- Conformance fixtures.
- Distribution packages.
Nevytvářej samostatný ADM Editor.

---

# 5. Standard governance
Navrhni vhodná verzovaná rozšíření podle aktuálních konvencí ADM.

Pracovní návrhy identifikátorů:

- `ADM_terrain_surface_v1`
- `ADM_physical_surface_v1`
- `ADM_material_displacement_v1`
Případně další přesně vymezená rozšíření.

Tyto názvy nejsou závazné. Ověř existující registry a naming conventions.

Každý nový kontrakt musí obsahovat:

- Normativní schéma.
- Datové typy.
- Jednotky.
- Výchozí hodnoty.
- Povolené rozsahy.
- Matematickou definici.
- Pravidla validace.
- Capability negotiation.
- Fallback behavior.
- Serialization requirements.
- Conformance fixtures.
- Backward compatibility.
Existující shader profily neměň.

Nové chování zaváděj pomocí nových verzí nebo explicitních rozšíření.

---

# 6. Resolve existing terrain palette discontinuities
Tato část má prioritu P0.

Před dalšími rozsáhlými změnami prozkoumej známý problém výběru materiálových vrstev.

Předchozí mise prokázala:

- Viditelné švy při více než čtyřech současně nenulových materiálových vahách.
- Rozdílné materiálové palety sousedních trojúhelníků.
- Zesílení problému při Height Based Blending.
- 54 konfliktních trojúhelníků při jednom exportu referenčního terénu.

## 6.1 Separate global and local material identity
Jednoznačně odděl:

- Globální identitu povrchu.
- Lokální index materiálu.
- Lokální shader slot.
- Prostorovou váhu povrchu.
- Primitive material palette.
Přemapování lokálních slotů nesmí měnit výsledný materiál na sdílené hranici.

## 6.2 Seam-aware palette generation
Implementuj deterministický algoritmus výběru materiálových palet respektující:

- Sdílené vertexy.
- Sdílené hrany.
- Sousední trojúhelníky.
- Sousední tiles.
- Různé geometrické LOD.
- Nepravidelné dlaždice.
- Globální identitu povrchů.
- Surface Noise.
- Biome transitions.
Přednostně řeš problém konzistentní redukcí vah a vhodnou prostorovou distribucí materiálových palet.

Nepoužívej nezávislé ořezávání vah každého trojúhelníku, pokud vytváří nekonzistentní hranice.

## 6.3 More than four active surfaces
Čtyřvrstvý shader nemůže přesně reprezentovat libovolnou kombinaci více než čtyř nenulových vah.

Prozkoumej a porovnej:

- Seam-consistent palette reduction.
- Region-based palette assignment.
- Material boundary refinement.
- Control-map-based material representation.
- Explicit wider-layer shader profiles.
- Texture-array-based representation.
Nevytvářej automaticky osmivrstvý shader bez technického vyhodnocení.

Pokud je širší shaderový profil potřebný, musí být samostatně verzovaný, volitelný a mít vlastní capability a fallback.

Zachovej plnou podporu čtyřvrstvých profilů.

## 6.4 Explicit conflict resolution
World Tile Editor musí umožnit:

- Zobrazení konfliktů materiálových palet.
- Identifikaci dotčených trojúhelníků.
- Zobrazení zahozených materiálových vah.
- Měření chyby redukce.
- Automatický návrh řešení.
- Ruční opravu.
- Strict export mode.
- Explicit approximate export mode.
Strict export nesmí vydat známý nekonzistentní výsledek za bezchybný.

Approximate export musí uvádět rozsah aproximace.

Nepotlačuj varování pouze proto, aby referenční projekt prošel.

## 6.5 Verification
Ověř skutečný shaderový výsledek, nikoliv pouze vertex weights.

Testuj:

- Dva až čtyři povrchy.
- Pět a více povrchů.
- Height Based Blending.
- POM.
- Permutace lokálních slotů.
- Různé LOD.
- Zakřivený terén.
- Nepravidelné dlaždice.
- Biomy bez společných povrchů.
Pro konfliktní vstupy dolož buď bezešvý aproximovaný výsledek s měřitelnou chybou, přesnou reprezentaci vhodným profilem, nebo explicitní odmítnutí exportu.

---

# 7. Terrain Control Maps

## 7.1 Purpose
Rozšiř prostorovou reprezentaci materiálových vah nezávisle na hustotě geometrie.

Control Map není barevná textura.

Jedná se o prostorová data řídící distribuci materiálů.

Musí být možné ji kombinovat s COLOR_1 a existujícím Height Based Blending.

## 7.2 Supported modes
Normativně definuj alespoň:

- `VERTEX_ONLY`
- `TEXTURE_RGBA`
- `TEXTURE_RGB_IMPLICIT`
- `VERTEX_MULTIPLY`
- `VERTEX_OVERRIDE`
- `VERTEX_MODULATE`
VERTEX_ONLY používá existující vertex weights.

TEXTURE_RGBA používá čtyři explicitní texturové váhy.

TEXTURE_RGB_IMPLICIT používá tři explicitní a jednu implicitní váhu:

```
w0 = max(0, 1 - R - G - B)
w1 = R
w2 = G
w3 = B
```
Následně normalizuj váhy.

Jednoznačně definuj pořadí a přemapování kanálů.

VERTEX_MULTIPLY násobí základní vertex weights texturovými vahami.

VERTEX_OVERRIDE umožňuje řízené nahrazení základních vah.

VERTEX_MODULATE umožňuje deterministickou korekci základních vah.

Definuj:

- Neutral values.
- Zero-total fallback.
- Missing-map behavior.
- Normalization.
- Weight bounds.
- Channel identity.
- Strength.
- Override mask, pokud je relevantní.

## 7.3 Sampling
Podporuj:

- Explicit UV set.
- UV scale and offset.
- World-space planar mapping.
- Sampler wrap modes.
- Linear sampling.
- GPU texture formats.
- Independent resolution.
- Mipmap filtering.
Control Maps jsou lineární data, nikoliv sRGB.

Zajisti korektní zachování vah při filtraci a mipmappingu.

## 7.4 Evaluation order
Definuj jednotnou posloupnost:

```
Base vertex weights
Control Map sampling
Control Map combination
Weight normalization
Per-layer texture projection
Per-layer parallax evaluation
Height sampling
Height Based Blending
Final material evaluation
```
Přesný vztah k existujícím shaderovým kontraktům normativně zdokumentuj.

Control Map nesmí být posouvána view-dependent parallaxem jednotlivých vrstev, pokud nový profil výslovně nedefinuje odlišné chování.

## 7.5 LOD and seam consistency
Stejná prostorová Control Map musí být použitelná napříč různými geometrickými LOD.

Zajisti:

- Global surface identity.
- Consistent UV phase.
- Tile-border sampling.
- Border padding.
- Mipmap continuity.
- Floating-origin independence.

---

# 8. World Tile Control Map authoring
Integruj Control Maps do existujícího World Tile Editoru.

Podporuj:

- Generování z biome rules.
- Generování z výšky terénu.
- Generování ze sklonu.
- Surface Noise.
- Roads.
- Surface Paint.
- Import externích masek.
- Ruční malování.
- Nastavitelné rozlišení.
- Export GPU textur.
- Přímé zobrazení jednotlivých vah.
Doporučená rozlišení:

- 128².
- 256².
- 512².
- 1024².
- 2048².
- 4096².
Podporuj další validní rozměry, pokud odpovídají bezpečnostním limitům.

Umožni uživateli zobrazit:

- Samostatné kanály.
- Jednotlivé povrchy.
- Dominantní povrch.
- Vertex weights.
- Control Map weights.
- Combined weights.
- Final height-adjusted weights.
- Palette conflicts.
Změna Control Map nesmí automaticky vyžadovat rebuild vizuální geometrie.

Výjimku představují explicitně vyžádané změny geometrie, palet nebo colliderů.

---

# 9. Macro Color Mapping
Implementuj volitelné makroskopické barevné mapování.

Účelem je potlačit jednotvárné zabarvení rozsáhlých ploch.

Podporuj:

- Macro Color Texture.
- Strength.
- UV scale.
- UV offset.
- UV set.
- World-space projection.
- Per-layer influence.
- Blend mode.
Minimální režimy:

- Multiply.
- Tint.
- Lerp.
Definuj jejich přesnou matematiku v lineárním barevném prostoru.

Výchozí hodnoty musí být neutrální.

Macro Color Map může být:

- Sdílená mezi materiály.
- Sdílená mezi dlaždicemi.
- Samostatná pro oblast terénu.
- Importovaná.
- Ručně malovaná.
- Procedurálně vytvořená authoring nástrojem.
World Tile Editor musí podporovat generování z biomů, výšky, sklonu, šumu a uživatelských barevných pravidel.

Macro Color nesmí být závislá na náhodné identitě konkrétní renderovací instance.

---

# 10. Macro Normal Mapping
Implementuj makroskopickou normal mapu reprezentující větší povrchové struktury.

Podporuj:

- Texture reference.
- Strength.
- Scale.
- Offset.
- UV set.
- World-space mapping.
- Per-layer influence.
Použij korektní metodu kombinování normál, například normativně definovaný Reoriented Normal Mapping.

Definuj:

- Coordinate space.
- Tangent frames.
- Normal orientation.
- BC5 reconstruction.
- Normal strength.
- Normalization.
- Missing-map fallback.
Ověř kombinaci:

```
Base normal
Macro normal
Detail normal
Final surface normal
```
Nepoužívej nekontrolované prosté sčítání normál.

---

# 11. Anti-tiling and stochastic sampling
Implementuj volitelné potlačení viditelného opakování textur.

Podporuj alespoň:

- `NONE`
- `RANDOMIZED_TILING`
- `STOCHASTIC_BLEND`
Parametry:

- Deterministic seed.
- World-space origin.
- Cell size.
- Rotation strength.
- Offset strength.
- Blend sharpness.
- Variation strength.
Přesné datové typy, rozsahy a algoritmus normativně definuj.

Stejné prostorové transformace musí být aplikovány na odpovídající:

- Albedo.
- Normal.
- Roughness.
- Metallic.
- AO.
- Height.
- Emission.
- Detail Maps.
Při rotaci nebo zrcadlení UV správně transformuj tangent-space normály.

Zohledni transformaci POM paprsků.

Definuj korektní texture derivatives a mip selection.

Zajisti:

- Determinism.
- Stabilní výsledek při pohybu kamery.
- Stabilní výsledek při změně LOD.
- Tile seams.
- Floating-origin independence.
- Nezávislost na pořadí načtení assetů.
Nezaváděj nedeterministickou fragmentovou náhodnost.

---

# 12. Triplanar Mapping
Implementuj volitelný výběr projekce jednotlivých materiálových vrstev.

Minimální režimy:

- `UV_MAPPING`
- `WORLD_PLANAR`
- `TRIPLANAR`
Podporuj:

- Physical texture scale.
- Projection origin.
- Projection axis.
- Triplanar sharpness.
- Projection weights.
- Normal-aware projection.
Normativně definuj:

- Výpočet projekčních vah.
- Orientaci jednotlivých rovin.
- Zrcadlení.
- Transformaci normál.
- Degenerate cases.
- Sampling.
- Blending.
Triplanar Mapping musí být využitelný nejen pro terény, ale také pro obecné statické modely.

Ověř kombinace s:

- Anti-tiling.
- Control Maps.
- Macro Maps.
- Height Based Blending.
- Detail Maps.
- AO.
- Parallax.
- POM.
- Self-shadowing.
Pokud některá kombinace není implementovatelná v konkrétním backendu, definuj explicitní fallback.

Nepředstírej plnou podporu kombinací, které nebyly ověřeny.

---

# 13. Detail Material Maps
Přidej univerzální podporu detailových textur.

Minimálně:

- Detail Albedo.
- Detail Normal.
- Detail Roughness.
Parametry:

- Texture reference.
- UV scale.
- UV offset.
- Strength.
- Blend mode.
- Fade start distance.
- Fade end distance.
Definuj neutrální výchozí hodnoty.

Chybějící textura nesmí měnit základní materiál.

Umožni sdílení detailových textur mezi více materiály.

Zajisti korektní:

- Color space.
- Normal blending.
- Mipmapping.
- Filtering.
- Distance fading.
- GPU encoding.
Detail Maps nesmí způsobovat nekontrolované aliasing artefakty.

---

# 14. Per-layer material controls

## 14.1 Normal Strength
Přidej nezávislou intenzitu normal map každé materiálové vrstvy.

Definuj přesnou matematiku.

## 14.2 Blend Softness
Umožni jednotlivým vrstvám definovat odlišnou měkkost materiálového přechodu.

Zachovej:

- Zero-weight preservation.
- One-hot preservation.
- Normalized weights.
- Permutation invariance.
- Numerical stability.
- Backward compatibility.
Existující Height Based Blending algoritmy neměň.

Použij nový profil.

## 14.3 Material Porosity
Přidej volitelný popisný parametr poréznosti povrchu.

Porosity může ovlivňovat materiálovou reakci na externě dodanou vlhkost.

Případná materiálová odezva musí mít přesně definovaný kontrakt.

Neimplementuj simulaci deště, počasí nebo vodního cyklu.

Aktuální environmentální hodnoty dodává engine nebo preview aplikace.

---

# 15. Parallax Self-shadowing
Implementuj univerzální lokální zastínění virtuálního materiálového reliéfu.

Využij existující heightmapy.

Nevyžaduj samostatnou shadow texture.

Navrhované parametry:

```
parallax_self_shadow_enabled
parallax_self_shadow_strength
parallax_self_shadow_min_steps
parallax_self_shadow_max_steps
parallax_self_shadow_bias
```
Přizpůsob názvy existujícím konvencím.

## 15.1 Normative algorithm
Definuj:

1. Virtuální průsečík POM paprsku s height fieldem.
2. Směr ke konkrétnímu zdroji světla.
3. Transformaci směru do správného tangent frame.
4. Bounded ray march směrem ke světlu.
5. Detekci překážek.
6. Výpočet lokální visibility.
7. Regulaci shadow strength.
Zajisti:

- Bounded iteration count.
- Grazing-angle handling.
- Numerical stability.
- Bias against self-intersection.
- Correct UV transforms.
- Missing-height fallback.
- Disabled behavior.
- Zero-strength behavior.
Definuj normativní testovací vektory.

## 15.2 Lighting behavior
Self-shadowing ovlivňuje příspěvek konkrétního přímého světla.

Nesmí automaticky ztmavovat:

- Emission.
- Albedo.
- Všechny ostatní světelné zdroje.
- Veškeré nepřímé osvětlení.
AO a Self-shadowing zůstávají oddělené technologie.

U vícevrstvých materiálů definuj korektní kombinaci jednotlivých výsledků.

## 15.3 Universal application
Podporuj vhodné profily:

- Terrain.
- Layered PBR.
- Two-layer surfaces.
- Obecné povrchy s heightmapou.
Nevytvářej technologii omezenou pouze na terrain shaders.

## 15.4 Preview
World Tile Editor musí umožnit změnu směru světla.

Uživatel musí být schopen přímo porovnat:

- POM.
- POM + Self-shadowing.
V Blenderu implementuj odpovídající dostupný preview nebo transparentně označenou aproximaci.

---

# 16. True Displacement Mapping
Zaveď samostatné volitelné rozšíření pro skutečné geometrické posunutí povrchu.

Důsledně odděl:

- Material height.
- Height Based Blending.
- Parallax.
- POM.
- Terrain elevation.
- True displacement.

## 16.1 Data contract
Minimálně:

- Displacement texture.
- Channel selection.
- Invert.
- Physical scale in meters.
- Reference height.
- Maximum displacement.
- Direction convention.
- UV mapping.
- Enable.
- Authored geometry state.
Příklad principu:

```
displacementMeters =
    (sampleHeight - referenceHeight) * scaleMeters
```
Definuj přesnou matematiku a pravidla omezení maximálního posunutí.

## 16.2 Renderer independence
ADM definuje požadovaný geometrický efekt, nikoliv konkrétní GPU implementaci.

Povol například:

- Offline subdivision.
- CPU-generated displaced mesh.
- GPU tessellation.
- Jiné kompatibilní řešení.
Nevyžaduj podporu hardware tessellation v každém ADM rendereru.

## 16.3 Geometry and bounds
Definuj:

- Conservative bounds.
- Tessellation or subdivision requirements.
- Displacement direction.
- Normal reconstruction.
- Tangent reconstruction.
- LOD behavior.
- Tile boundary continuity.
- Fallback.
Displacement nesmí bez explicitního požadavku měnit kolizní geometrii.

Uživatel musí mít možnost vytvořit odpovídající collider jako samostatný authoring krok.

## 16.4 Authoring and baking
Blender plugin musí umožnit:

- Nastavení displacementu.
- Skutečný preview.
- Export deklarativního displacementu.
- Volitelné zapečení do geometrie.
- Export již deformované geometrie.
Zabraň dvojité aplikaci displacementu.

World Tile Editor musí podporovat bezpečné použití displacementu na terénu.

Při nemožnosti runtime preview může nabídnout bounded offline geometry preview.

## 16.5 Reference comparison
Vytvoř originální cihlový materiál.

Na kouli a rovinné ploše demonstruj:

1. Albedo.
2. Normal Mapping.
3. Normal + AO.
4. Parallax.
5. POM.
6. POM + Self-shadowing.
7. True Displacement.
Dolož skutečné rendery z více úhlů kamery a světla.

Zvláště demonstruj změnu siluety při skutečném displacementu.

---

# 17. Material Distance LOD
Zaveď volitelné deklarativní úrovně materiálového detailu.

Material Distance LOD je nezávislý na geometrickém LOD.

Podporuj doporučené rozsahy vzdáleností v metrech.

Příklad:

```
NEAR:
    Full PBR
    Height Blend
    POM
    Self-shadowing
    Detail Maps
    Macro Maps
    Anti-tiling

MID:
    PBR
    Height Blend
    Optional Parallax
    Optional Detail Maps
    Macro Maps

FAR:
    Simplified PBR
    Macro Maps
    Reduced sampling
```
Nevynucuj univerzální vzdálenosti pro všechny assety.

Podporuj plynulé přechody, pokud jsou smysluplné.

Zabraň výrazným změnám barev, normál a materiálových vah při přepnutí.

Engine může použít vlastní quality policy.

ADM poskytuje deklarativní preference a dostupné vlastnosti.

---

# 18. GPU texture architecture and BC5 compatibility
Tato část řeší známý technický dluh předchozí mise.

## 18.1 Core PBR BC5
Současná specifikace má omezení:

- BC5 ukládá R a G.
- Pokročilý renderer rekonstruuje Z.
- Core PBR fallback očekává RGB normal mapu.
- Současný dvoukanálový fallback kontrakt neumožňuje jednoduše reprezentovat obě očekávání jedinou texturou.
Navrhni verzované řešení umožňující:

- Zachovat originální BC5 GPU bytes.
- Poskytnout správnou rekonstruovanou RGB normal mapu.
- Zachovat sampler.
- Zachovat UV set.
- Zachovat normal strength.
- Podporovat samostatné core-PBR materiály.
- Podporovat layered shaders.
- Podporovat embedded i external images.
- Zabránit nejednoznačné interpretaci dat.
Neměň význam historických BC5 kontraktů.

Nepoužívej tichou rekompresi jako řešení.

Zvaž explicitní role-dependent fallback nebo jinou jednoznačně verzovanou reprezentaci.

## 18.2 Texture preservation
Zachovej existující per-map GPU encoding.

Kompatibilní originální GPU textury mají být standardně zachovány byte-for-byte.

Konverze musí být explicitní nebo transparentně zdokumentovaná.

Zachovej:

- R16 precision.
- Multichannel 16-bit source data.
- Mipmap payloads.
- BC5 normal semantics.
- BC7 color space.
- Embedded and external textures.

## 18.3 Texture packing
Rozvíjej existující interní packing stejně velkých scalar maps.

Nedovol:

- Neoprávněný resampling.
- Ztrátu R16 precision.
- Ztrátu kanálů.
- Nekompatibilní color-space kombinace.
- Tichou ztrátu materiálové vlastnosti.
Interní renderer packing nesmí bez explicitní volby měnit zdrojová ADM data.

## 18.4 Texture arrays and resource budgets
Vyhodnoť vhodnost texture arrays, shared material resources a dalších optimalizací.

Zohledni:

- Rozdílná rozlišení.
- Rozdílné formáty.
- Mipmaps.
- Color space.
- Samplers.
- Hardware texture-unit limits.
- GPU memory.
- Shader sampling cost.
Nevyžaduj Vulkan descriptor indexing nebo jinou konkrétní API technologii v základním ADM kontraktu.

Reference preview musí umět explicitně oznámit překročení dostupného rozpočtu.

---

# 19. Physical Surface System
Tato část má prioritu P0.

Rozšiř existující ADM physical materials.

Nevytvářej paralelní fyzikální formát.

## 19.1 Semantic surface identity
Každý fyzikální materiál musí být schopný deklarovat:

- Stable identity.
- Surface type.
- Surface subtype.
- Semantic tags.
- Existující fyzikální vlastnosti.
Vizuální a fyzikální materiály jsou nezávislé.

Například:

```
Visual: Wet grass
Physical: Soft mud
```
Tato kombinace musí být validní.

## 19.2 Standard surface registry
Vytvoř verzovaný machine-readable katalog.

Minimální kategorie:

- Unknown.
- Grass.
- Soil.
- Mud.
- Sand.
- Rock.
- Gravel.
- Snow.
- Ice.
- Moss.
- Leaves.
- Wood.
- Concrete.
- Brick.
- Asphalt.
- Metal.
- Glass.
- Plastic.
- Rubber.
- Fabric.
- Organic.
Katalog nesmí být omezený pouze na terén.

Musí být využitelný u libovolných ADM assetů.

## 19.3 Surface subtypes
Podporuj například:

```
grass.short
grass.long
grass.dry
grass.lush

soil.dry
soil.wet
soil.forest
soil.farmland

mud.soft
mud.hard

sand.dry
sand.wet

gravel.fine
gravel.coarse

snow.fresh
snow.compacted

rock.granite
rock.limestone
rock.sandstone

wood.raw
wood.processed
```
Jedná se o příklady, nikoliv pevně předepsané finální identifikátory.

Zaveď kvalifikované uživatelské typy podle naming conventions ADM.

Definuj fallback neznámých typů.

Uživatelské typy musí být zachovány při round-trip.

## 19.4 Surface versus biome
Rozlišuj biom a fyzikální povrch.

Poušť je biom.

Může obsahovat:

- Sand.
- Rock.
- Gravel.
- Dry soil.
Biome metadata v authoring nástrojích nesmí nahrazovat fyzikální klasifikaci.

## 19.5 Physical parameters
Zachovej existující physical material properties.

Nepřidávej duplicitní friction nebo restitution parametry s jiným významem.

Příklady nových dat:

- Surface type.
- Subtype.
- Semantic tags.
- Optional descriptive metadata.
ADM nesmí definovat konkrétní gameplay reakce.

Neukládej instrukce:

- Generate vegetation.
- Play footstep sound.
- Reduce player movement speed.
- Spawn particles.
- Apply gameplay damage.
Engine rozhoduje o těchto akcích na základě dat.

---

# 20. Collider material assignment
Prozkoumej existující collider kontrakty a rozšiř pouze skutečně chybějící části.

Podporuj:

- Jeden fyzikální materiál pro celý collider.
- Fyzikální materiály jednotlivých trojúhelníků.
- Lokální material tables, pokud odpovídají existující architektuře.
- Stabilní material references.
- Jednoduché collider shapes.
- Triangle mesh colliders.
Validuj všechny indexy a vazby.

Zachovej fyzikální materiály při:

- Triangulaci.
- Importu.
- Exportu.
- Přesunu assetu.
- Blender round-trip.
- Project reload.
Implementuj referenční Surface Query funkci.

Na základě existujícího kolizního zásahu musí být možné jednoznačně získat:

```
Collider ID
Triangle index
Physical material ID
Surface type
Surface subtype
Semantic tags
Friction
Restitution
```
Nevytvářej kompletní fyzikální engine.

Referenční funkce má demonstrovat interpretaci standardizovaných dat.

---

# 21. Independent Terrain Collision Generator
Integruj do World Tile Editoru generování samostatných colliderů.

Kolizní geometrie nesmí být povinně totožná s vizuální geometrií.

Podporuj:

- Independent collision resolution.
- Geometric error tolerance.
- Simplification.
- Material boundary refinement.
- Triangle budget.
- Independent export configuration.
Zachovej geometrickou kontinuitu sousedních colliderů.

## 21.1 Automatic physical classification
Každý povrch v Surface Library musí mít možnost odkazovat na fyzikální materiál.

Automatická klasifikace může využít:

- Biome rules.
- Surface Paint.
- Control Maps.
- Roads.
- Stable dominant material weights.
Nepoužívej:

- View-dependent POM UV.
- Camera-dependent LOD.
- Lighting.
- Final pixel color.
- View-dependent shader weights.
Fyzikální povrch musí být stabilní nezávisle na rendereru.

## 21.2 Boundary refinement
Umožni zpřesnění kolizní geometrie v okolí fyzikálních materiálových hranic.

Například:

- Grass / road.
- Mud / rock.
- Snow / ice.
- Sand / gravel.
Definuj:

- Maximum subdivision depth.
- Minimum triangle size.
- Maximum triangle count.
- Boundary error tolerance.
- Deterministic tie-breaking.
Zabraň neomezenému růstu geometrie.

## 21.3 Independent physical paint
Přidej samostatný režim malování fyzikálních povrchů.

Ruční klasifikace má přednost před automatickou, pokud uživatel nezvolí jinak.

Změna vizuálního materiálu nesmí automaticky odstranit ruční fyzikální klasifikaci.

Umožni reset vybrané oblasti na automatické hodnoty.

## 21.4 Collision diagnostics
World Tile Editor musí zobrazovat:

- Collision wireframe.
- Physical material colors.
- Material boundaries.
- Triangle counts.
- Geometry error.
- Surface information under cursor.
- Physical material identity.
- Unassigned or unknown materials.
Umožni samostatné zobrazení vizuální a kolizní geometrie.

---

# 22. World Tile Editor integration
Rozšiř existující World Tile Editor.

Nevytvářej novou aplikaci ani paralelní renderer bez prokázaného technického důvodu.

Využij existující custom shader infrastrukturu:

`appartus_world_tile/awt/gui/preview_shader.py`

Ověř její aktuální stav.

## 22.1 Renderer architecture
Uspořádej nové technologie do rozšiřitelných shaderových komponent.

Odděl:

- Parameter binding.
- Texture binding.
- Mapping.
- Control Map evaluation.
- Parallax evaluation.
- Height blending.
- Normal composition.
- Macro Maps.
- Detail Maps.
- Self-shadowing.
- Diagnostics.
- Resource budgeting.
Nepřidávej neudržitelné množství vzájemně nezávislých shader replacements bez společné architektury.

Využij sdílenou referenční matematiku ADM.

## 22.2 Preview modes
Zachovej a rozšiř:

- Fast Geometry Preview.
- Visual Material Preview.
- Detailed Terrain Preview.
- Multi-surface Preview.
- Sphere.
- Plane.
- Terrain Relief.
Přidej:

- Control Map Preview.
- Macro Color Preview.
- Macro Normal Preview.
- Final Weight Preview.
- Material Palette Diagnostics.
- Physical Surface Preview.
- Collision Mesh Preview.
- Displacement Preview.
Umožni porovnávání jednotlivých materiálových efektů před a po aktivaci.

## 22.3 Quality settings
Zaveď vhodné úrovně:

- Fast.
- Standard.
- Advanced.
- Full.
Uživatel musí mít možnost samostatně vypnout drahé efekty.

Změna preview quality nesmí měnit exportovaná ADM data.

Nedovol tiché snižování kvality exportu kvůli omezení preview rendereru.

## 22.4 Surface Library
Integruj authoring všech nových vlastností.

Zachovej současnou práci s:

- Texture sets.
- Per-map GPU encoding.
- Material presets.
- Texture repeat.
- Surface Noise.
- Biomes.
- Roads.
- Paint data.
Při editaci jedné vlastnosti nesmí docházet ke ztrátě nesouvisejících hodnot.

## 22.5 Persistence
Rozšiř AWTP a material preset formáty verzovaným způsobem.

Zachovej načítání všech dosud podporovaných verzí.

Zachovej relativní cesty.

Neznámé vlastnosti nesmí být tiše zahozeny.

Pokud nelze bezpečně interpretovat neznámé reference, uživatele informuj a zabraň destruktivnímu exportu.

---

# 23. Export Changed and dependency tracking
Rozlišuj nezávislé změny:

- Visual geometry.
- Terrain rules.
- Vertex weights.
- Control Maps.
- Macro Maps.
- Detail Maps.
- Shader settings.
- GPU encoding.
- Physical materials.
- Collision geometry.
- Physical paint.
Změna fyzikálního materiálu nesmí zbytečně přegenerovat visual mesh.

Změna Macro Color nesmí přegenerovat collider.

Změna preview kvality nesmí invalidovat ADM export.

Změna obsahu textury musí invalidovat skutečně dotčené assety.

Změna nepoužívaného povrchu nesmí bezdůvodně invalidovat celý svět.

Zachovej:

- Content fingerprints.
- Selective invalidation.
- Atomic publication.
- Validated export.
- Source-byte preservation.
Ověř opakovaný export beze změn.

---

# 24. Seamless Terrain requirements
Tato část je kritická.

Ověř kontinuitu:

- Visual geometry.
- Collision geometry.
- UV phase.
- Control Maps.
- Macro Color.
- Macro Normal.
- Anti-tiling.
- Triplanar.
- Detail Maps.
- Height Based Blending.
- POM.
- Self-shadowing.
- True Displacement.
- Material palette selection.
Testuj:

- Stejně velké tiles.
- Nepravidelné krajní tiles.
- Různé LOD.
- Zakřivené povrchy.
- Rozdílné lokální sloty.
- Rozdílné primitive grouping.
- Více než čtyři povrchy.
- Velké world-space souřadnice.
- Floating origin.
- Biome transitions.
- Roads.
Zachovej současné RTIN geometrické garance.

Nepovažuj shodu vertex weights za dostatečný důkaz vizuální kontinuity.

Používej skutečné renderovací testy.

Rozlišuj geometrické, materiálové a kolizní švy.

---

# 25. Blender plugin integration
Rozšiř existující ADM Blender plugin.

Integruj:

- Nové extension metadata.
- Nové shader profiles.
- Shader Registry.
- Material authoring.
- Control Maps.
- Macro Color.
- Macro Normal.
- Anti-tiling.
- Triplanar.
- Detail Maps.
- Per-layer controls.
- Self-shadowing metadata.
- Displacement.
- Physical Surface Registry.
- Collider material assignment.

## 25.1 Collider authoring
Umožni:

- Přiřazovat fyzikální materiály celým colliderům.
- Přiřazovat fyzikální materiály jednotlivým plochám.
- Zobrazovat surface types barvou.
- Kontrolovat neplatné reference.
- Zachovat přiřazení po triangulaci.
- Importovat World Tile collidery.
- Exportovat upravené collidery.

## 25.2 Material preview
Implementuj skutečné Blender node groups tam, kde lze normativní kontrakt reprodukovat.

Existující Blender native POM zůstává známým omezením.

Prozkoumej vhodnou implementaci bez narušení kompatibility Blenderu.

Pokud přesný efekt nelze realizovat, zajisti:

- Zachování všech parametrů.
- Nejlepší dostupnou funkční aproximaci.
- Explicitní označení omezení.
- Ověřený import/export round-trip.
Nevydávej Bump Mapping za skutečný POM.

Nevydávej AO za Parallax Self-shadowing.

Nevydávej metadata-only podporu za rendererovou konformitu.

## 25.3 Stability
Zachovej opravy předchozí mise:

- Stable dynamic enums.
- Profile switching.
- Inactive parameter preservation.
- Registration rollback.
- Deferred migrations.
- Shader parameter ownership.
- Bounded test processes.
Prozkoumej existující dependency-cycle warnings.

Oprav je tam, kde lze bezpečně identifikovat příčinu.

Nevytvářej rozsáhlý refaktor nesouvisejících částí pluginu pouze kvůli odstranění diagnostiky.

---

# 26. Forward compatibility
Navazuj na existující unknown extension preservation.

Rozlišuj:

- Známá normativní rozšíření.
- Neznámá volitelná rozšíření.
- Neznámá povinná rozšíření.
- Opaque metadata.
- Známé přemapovatelné reference.
- Neznámé reference.
Neznámé povinné capability nesmí být tiše ignorovány.

Opaque JSON lze zachovat, ale bez znalosti jeho schématu nelze automaticky garantovat korektní přemapování všech referencí.

Prozkoumej možnost verzovaného deklarativního popisu referencí rozšíření, pokud je pro tuto misi skutečně potřebný.

Neimplementuj nebezpečné heuristiky, které náhodné číselné hodnoty interpretují jako indexy ADM objektů.

Nevytvářej falešnou garanci plné round-trip kompatibility.

---

# 27. Existing ecosystem integration
Audituj všechny relevantní existující consumery.

Podle jejich odpovědnosti aktualizuj:

- SDK.
- CLI.
- Validators.
- Reference mathematics.
- Reference renderers.
- Existing viewers.
- Importers.
- Exporters.
- Blender plugin.
- World Tile Editor.
Pro každou technologii eviduj:

- Full.
- Partial.
- Approximation.
- Fallback.
- Metadata preservation.
- Unsupported.
- Not applicable.
Neupravuj externí repozitáře.

Nevytvářej závislost ADM na Raven Engine, Echo3D, Unity, Unreal Engine nebo jiném konkrétním enginu.

Nevyžaduj konkrétní renderovací API pro základní konformitu formátu.

---

# 28. Reference assets
Vytvoř vlastní procedurální materiály.

Nepoužívej proprietární herní assety.

Minimálně:

- Grass.
- Dry Grass.
- Forest Soil.
- Mud.
- Gravel.
- Sand.
- Rock.
- Snow.
- Brick.
- Cobblestone.
Podle potřeby vytvoř:

- Albedo.
- Normal.
- Roughness.
- AO.
- Height.
- Detail Maps.
- Macro Maps.
Zachovej deterministickou generaci testovacích materiálů.

## 28.1 Advanced Material Showcase
Vytvoř ADM scénu umožňující izolovat:

- Classic blending.
- Height blending.
- Control Maps.
- Macro Color.
- Macro Normal.
- Anti-tiling.
- Triplanar.
- Detail Maps.
- POM.
- Self-shadowing.
- True Displacement.
Každý efekt musí mít funkční srovnávací variantu.

## 28.2 Advanced Terrain Reference World
Vytvoř přenositelný AWTP projekt.

Musí obsahovat:

- Více sousedních tiles.
- Více geometrických LOD.
- Nepravidelné krajní tiles.
- Travnaté pláně.
- Skalnaté svahy.
- Hlínu.
- Bláto.
- Písek.
- Sníh.
- Cesty.
- Několik biomů.
- Více než čtyři povrchy na úrovni světa.
- Control Maps.
- Macro Maps.
- Anti-tiling.
- Triplanar.
- Detail Maps.
- Height Based Blending.
- POM.
- Self-shadowing.
Součástí musí být samostatná kolizní geometrie s fyzikálními materiály.

Demonstruj automatické i ruční přiřazování fyzikálních povrchů.

Projekt musí být možné:

1. Zkopírovat mimo repozitář.
2. Otevřít.
3. Zobrazit.
4. Upravit.
5. Vygenerovat geometrii a collidery.
6. Exportovat validní ADM.
Bez ručního opravování cest.

## 28.3 Physical Surface Reference Asset
Vytvoř samostatný ADM asset s několika fyzikálními povrchy.

Demonstruj rozdílný vizuální a fyzikální materiál.

Přidej referenční surface queries s očekávanými výsledky.

## 28.4 Brick Material Showcase
Vytvoř kouli a rovinnou plochu demonstrující rozdíl mezi normal mapou, POM, Self-shadowing a skutečným displacementem.

Výsledkem musí být skutečné rendery, nikoliv pouze metadata.

---

# 29. Performance requirements
ADM musí zůstat vhodný pro real-time rendering.

Nevyžaduj současnou aktivaci všech efektů.

Minimalizuj zbytečné:

- Texture samples.
- POM iterations.
- Self-shadowing iterations.
- Texture bindings.
- Decoded texture copies.
- Geometry rebuilds.
- Shader recompilation.
- Resource allocation.
Implementuj bounded resource budgets.

Využij existující caching.

Měř:

- Preview rendering time.
- Texture preparation time.
- GPU texture base-level footprint.
- Odhad nebo skutečnou GPU memory podle dostupnosti měření.
- Shader resource requirements.
- Control Map generation.
- Collision generation.
- Triangle counts.
- Export time.
- Peak process memory.
- Asset sizes.
Rozlišuj CPU čas, GPU čas a celkový čas operace.

Nevymýšlej naměřené hodnoty.

Neprezentuj měření jednoho malého projektu jako důkaz škálovatelnosti celého otevřeného světa.

---

# 30. Automated verification
Implementuj automatické testy všech nových normativních kontraktů.

## Material palettes

- Global material identity.
- Slot permutation.
- Shared-edge consistency.
- Five-surface conflicts.
- Exact versus approximate export.
- Mixed LOD.
- Curved terrain.
- Strict conflict rejection.

## Control Maps

- Explicit RGBA.
- Implicit fourth layer.
- Channel remapping.
- Multiply.
- Override.
- Modulate.
- Zero weights.
- Normalization.
- Filtering.
- Mipmaps.
- Tile borders.

## Macro Maps

- Neutral defaults.
- Linear color blending.
- Normal combination.
- Shared world-space sampling.
- Missing-map fallback.

## Anti-tiling

- Determinism.
- Consistent layer transforms.
- Normal orientation.
- Mip selection.
- Tile seams.
- Camera movement.

## Triplanar

- Axis orientation.
- Projection weights.
- Normal transformations.
- Height sampling.
- Degenerate cases.
- Combined material effects.

## Self-shadowing

- Flat heightfield.
- Single obstacle.
- Multiple obstacles.
- Opposite light directions.
- Disabled behavior.
- Zero strength.
- Grazing angle.
- Iteration bounds.
- Missing heightmap.
- Direct-light isolation.

## Displacement

- Zero displacement.
- Physical scale.
- Reference height.
- Maximum displacement.
- Conservative bounds.
- Normal reconstruction.
- Tile seams.
- No double application.
- No implicit collider modification.

## Physical surfaces

- Standard surface IDs.
- Custom IDs.
- Invalid IDs.
- Unknown-type fallback.
- Tags.
- Collider references.
- Triangle material assignments.
- Surface queries.
- Blender round-trip.

## GPU textures

- BC5 core-PBR fallback.
- Source-byte preservation.
- Embedded images.
- External images.
- R16 precision.
- Mip chains.
- Samplers.
- Explicit re-encoding.
- Resource limits.

## World Tile

- Legacy projects.
- New project persistence.
- Material presets.
- UI bindings.
- Control Map generation.
- Physical paint.
- Collision simplification.
- Collision material boundaries.
- Selective invalidation.
- Atomic export.
- Portable reference project.
- Actual render comparisons.

## Blender

- Actual Blender runtime.
- Registration.
- Profile switching.
- Material authoring.
- Node generation.
- Collider assignment.
- Import/export.
- Save/reload.
- Round-trip.
- Real render or bake tests.
- World Tile imports.
Neakceptuj přeskočený test jako důkaz úspěšné verifikace.

---

# 31. Validation and safety
Audituj nové vstupní a výpočetní hranice.

Minimálně:

- Invalid dimensions.
- Invalid DDS/KTX2.
- Corrupt mipmaps.
- Invalid UV references.
- NaN and Inf.
- Invalid enums.
- Out-of-range weights.
- Shader iteration limits.
- Texture allocation limits.
- Integer overflow.
- Displacement bounds.
- Collision triangle budgets.
- Invalid physical material references.
- Path traversal.
- Symbolic links.
- Atomic export.
- Resource cleanup.
Veškeré generátory geometrie a shader loops musí být omezené.

Oprav všechny nalezené řešitelné problémy.

---

# 32. Explicitly out of scope
Neimplementuj:

- Vegetation distribution.
- Procedural grass spawning.
- Tree scattering.
- Object spawning.
- Gameplay surface effects.
- Footstep audio systems.
- Particle spawning systems.
- Physics engine.
- Character controller.
- Dynamic weather simulation.
- World streaming runtime.
- Network replication.
- Engine-specific GPU culling.
- Clothing System.
- PED Wardrobe System.
- Proprietary Rockstar compatibility.
ADM poskytuje sémantická data a materiálové vlastnosti.

Engine rozhoduje, jak je použije.

---

# 33. Documentation
Aktualizuj:

- Main README.
- ADM Specification.
- Extension Registry.
- Capability Registry.
- Shader Registry.
- Physical Surface Registry.
- Normative profiles.
- Blender documentation.
- World Tile documentation.
- Migration guide.
- Fixture catalog.
- CHANGELOG.
- SPEC_GAPS.
- Conformance requirements.
- Implementation support matrix.
Dokumentace musí rozlišovat skutečnou implementaci, normativní podporu, referenční matematiku, aproximaci a nepodporované vlastnosti.

---

# 34. Milestones

## M1 – Baseline and architecture audit

- Archive previous mission.
- Verify baseline.
- Review technical debt.
- Establish regression baseline.
- Create persistent mission state.

## M2 – Terrain palette consistency

- Global surface identity.
- Seam-aware palette generation.
- Conflict diagnostics.
- Strict and approximate export.
- Rendered seam tests.

## M3 – Physical Surface Standard

- Surface Registry.
- Physical materials.
- Semantic tags.
- Collider assignments.
- Surface queries.

## M4 – Terrain Control Maps

- Normative contracts.
- Reference math.
- Sampling.
- Channel semantics.
- Seam behavior.

## M5 – Macro Mapping

- Macro Color.
- Macro Normal.
- Shared projection.
- Reference evaluation.

## M6 – Advanced texture projection

- Anti-tiling.
- Stochastic sampling.
- Triplanar.
- Combined map transformations.

## M7 – Detail Material System

- Detail Maps.
- Normal Strength.
- Blend Softness.
- Porosity.

## M8 – Advanced Relief Rendering

- Parallax Self-shadowing.
- True Displacement.
- Material Distance LOD.

## M9 – GPU resource architecture

- BC5 core-PBR solution.
- Source preservation.
- Texture packing.
- Resource budgeting.
- Performance.

## M10 – World Tile physical integration

- Physical Material Library.
- Automatic classification.
- Physical painting.
- Independent collision generation.
- Boundary refinement.
- Collision diagnostics.

## M11 – World Tile visual integration

- Control Map authoring.
- Macro Map authoring.
- Advanced preview.
- Shader integration.
- Persistence.
- Export Changed.
- ADM export.

## M12 – Blender and ecosystem

- Blender authoring.
- Shader nodes.
- Collider materials.
- Import/export.
- Round-trip.
- Remaining consumers.
- Support matrix.

## M13 – Reference assets

- Procedural material library.
- Advanced Terrain Reference World.
- Material Showcase.
- Brick Showcase.
- Physical Surface Reference Asset.
- Actual renders.

## M14 – Full verification and distribution

- Complete regression suite.
- Package audits.
- Renderer tests.
- Performance measurements.
- Documentation.
- Distribution.
- Final audit.
Pokračuj mezi milníky automaticky.

---

# 35. Build and distribution policy
Nevytvářej novou distribuční verzi po každé drobné změně.

Používej během implementace:

- Targeted tests.
- Check-only builds.
- Temporary candidate packages.
- Bounded integration tests.
Release version bump proveď po stabilizaci příslušné distribuce.

Zkontroluj, že balíčky neobsahují:

- Vnořené staré ZIP archivy.
- Lokální vývojové soubory.
- Nepotřebné cache.
- Proprietární testovací textury.
- Neplatné absolutní cesty.
Ověř balíčky mimo vývojový workspace.

Blender extension testuj v izolovaných preferences i izolovaném extension repository.

Nenahrazuj uživateli jeho existující instalaci během automatických testů.

Pokud nejsou dostupné další platformy, zaznamenej přesný rozsah ověření.

Nevydávej Windows-only testy za multiplatformní certifikaci.

---

# 36. Definition of Done
Mise je dokončena pouze tehdy, když:

1. Nové technologie mají jednoznačné normativní kontrakty.
2. Historické shader profily zůstávají kompatibilní.
3. Známé materiálové konflikty mají explicitní a ověřené řešení.
4. World Tile Editor podporuje authoring nových technologií.
5. Pokročilé materiály jsou skutečně vizualizovatelné.
6. Control Maps fungují nezávisle na hustotě geometrie.
7. Fyzikální materiály jsou nezávislé na vizuálních materiálech.
8. Collidery lze generovat a editovat samostatně.
9. Blender plugin podporuje authoring a round-trip.
10. Unsupported features nejsou tiše zahozeny.
11. Core-PBR BC5 compatibility má normativní řešení.
12. Referenční AWTP projekt je přenositelný.
13. Referenční ADM assety projdou validací.
14. Jsou doloženy skutečné rendery.
15. Jsou doloženy seam tests.
16. Jsou doloženy relevantní performance tests.
17. Distribuční balíčky jsou funkční.
18. Dokumentace odpovídá skutečné implementaci.
19. Všechny zbývající nedostatky jsou explicitně evidovány.
20. Byl dokončen finální audit původního zadání.
Pokud je požadavek splnitelný, pokračuj v jeho implementaci.

Pokud je požadavek objektivně blokován, dolož přesný technický důvod.

Neoznačuj neověřené funkce za dokončené.

---

# 37. Final report
Po dokončení vytvoř:

- `.ai/FINAL_REPORT.md`
- `.ai/TECHNICAL_DEBT.md`
FINAL_REPORT musí obsahovat:

- Baseline commit.
- Výsledný commit nebo přesný stav workspace.
- Dokončené milníky.
- Nové extension IDs.
- Nové capabilities.
- Nové shader profiles.
- Physical Surface Registry.
- Consumer support matrix.
- Test results.
- Passed, failed and skipped counts.
- Render results.
- Seam results.
- Collision results.
- Performance measurements.
- Package verification.
- Reference asset locations.
- Portable AWTP project location.
- Brick Showcase location.
- Skutečné screenshoty a rendery.
- Známá omezení.
TECHNICAL_DEBT musí obsahovat:

- Příčinu každého zbývajícího problému.
- Závažnost.
- Současný workaround.
- Doporučené budoucí řešení.
- Odkaz na příslušný zdrojový kód nebo test.
Před ukončením práce znovu načti celé MISSION.md.

Porovnej každý požadavek se skutečnou implementací.

Znovu otevři předčasně uzavřené checkboxy.

Nezastavuj se u dokumentace.

Nezastavuj se u referenční matematiky.

Nezastavuj se pouze u zelených unit testů.

Cílem je skutečně použitelný, vizuálně pokročilý a ověřený ADM Advanced Terrain & Physical Surface System.

Continue autonomously until completion.