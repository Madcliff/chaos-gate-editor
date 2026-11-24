# Chaos Gate – Daemonhunters internals

Notes on how the game stores classes, skill trees, abilities and weapons, gathered while building the editor. Everything here applies to Steam build `0706ef9` (`version.txt`), a Unity 2021.3.6f1 IL2CPP build.

Each fact is marked:

- **Confirmed in-game** – tested by launching the game.
- **Verified in files** – checked against the game files, but not observed in-game.
- **Inferred** – a reasonable reading that hasn't been tested.

## Files

All paths are relative to the `ChaosGate` install folder.

| File | What it holds |
|---|---|
| `ChaosGate_Data/StreamingAssets/bundles/data_assets` | Gameplay data: classes, perks, abilities, upgrades, weapons, status effects and more. About 5,500 MonoBehaviour assets. |
| `ChaosGate_Data/StreamingAssets/bundles/manifest.dat` | JSON index that maps asset paths to bundles. |
| `ChaosGate_Data/StreamingAssets/bundles/localization/english` | English text tables. |
| `ChaosGate_Data/level5` | Scene with the promotion and Commune screens, including every knight skill-tree button. |
| `GameAssembly.dll` | Compiled game code (IL2CPP). |
| `ChaosGate_Data/il2cpp_data/Metadata/global-metadata.dat` | Class, field and method names for the compiled code (metadata version 29). |

The Unity log is at `…/compatdata/1611910/pfx/drive_c/users/steamuser/AppData/LocalLow/Complex Games Inc_/GreyKnights/Player.log` on Linux/Proton. On Windows, it's in `%USERPROFILE%\AppData\LocalLow\Complex Games Inc_\GreyKnights\`. Asset lookup failures and exceptions appear there.

## data_assets bundle

*Verified in files.* `data_assets` is an uncompressed UnityFS bundle with type trees, so UnityPy can read and write every asset field by name. Bundle container paths are lowercase, such as `assets/assetbundles/dataassets/classperks/librarian_psychicshriek.asset`. Each asset's `m_Name` and `id` match its file name.

*Confirmed in-game.* A bundle re-saved by UnityPy with `packer="original"` loads correctly. The editor's v0.2.0 output was installed when the extra Librarian perk appeared.

### PathIDs are 64-bit

Asset references use 64-bit PathIDs such as `-1562094628324899010`, which exceed what a JavaScript number or a double can store exactly. The online Unity editor rounded `-1562094628324899010` to `…012` in `ForceStrike_Stun_2`, which broke that asset's script reference. Keep PathIDs as integers or decimal strings in any tooling.

### Main asset types

| Script | Count | Key fields and links |
|---|---|---|
| `ClassData` | 89 | `perks` (PPtrs to default perks), `abilities`, `archetype`, `OtherData` (`isBaseClass`) |
| `ClassPerksData` | 462 | `id`, `ownerClass` (PPtr to ClassData), `prerequisites` (perk ID keys), `abilities` and `upgrades` (ID keys granted), `allowedWeaponClasses`, `allowedArmourClasses` |
| `ActiveAbilityData` | 402 | Costs, range, damage, `instantEffects`, `statusEffects`, `psyAbility`, localisation keys |
| `PassiveAbilityData` / `AutoAbilityData` | 408 / 104 | Like active abilities, without activation |
| `AbilityUpgradeData` | 442 | `baseAbilities` (keys of abilities it modifies), added effects, damage bonuses |
| `WeaponData` | 406 | `equipmentClass` (PPtr to WeaponClassData), `tier`, `purchaseCost`, `equipmentSlots` (granted attack abilities), stats, `OtherData` (`RequiredPurchaseUnlock`) |
| `WeaponClassData` | 118 | Weapon family, such as `WC_PowerFist` |

Most cross-references are by ID string (`{"key": "SomeId"}`), not PPtr. *Verified in files:* no master list of weapons, perks or abilities exists in `data_assets`. *Inferred:* the game finds assets by path.

### Knight skill trees

*Verified in files.* Each of the 10 knight classes has 37 `ClassPerksData` entries: one default perk with no prerequisites, listed in `ClassData.perks` and granted automatically, plus 36 perks that each have a tree button. The tree is the graph formed by `prerequisites`. Assassins have 18–21 perks and use a separate system (`AssassinLevelPerkConfig`), which hasn't been investigated.

## manifest.dat and asset lookup

*Verified in files.* `manifest.dat` is compact JSON: `{"bundleInfos": [...], "defaultVariant": "", "version": "1.…"}`. The `data_assets` row lists every asset path in original case, such as `Assets/AssetBundles/DataAssets/ClassPerks/Librarian_PsychicShriek.asset`, along with `hash`, `crc` and `fileSize`.

*Confirmed in-game.* The game builds a lookup path from an asset's ID, for example `AssetBundles/DataAssets/ClassPerks/<id>.asset`, and resolves it through `manifest.dat`. An asset that exists in `data_assets` but is missing from the manifest fails. `Player.log` shows `no asset path info found for path: …` and `missing bundle for: …`, followed by a `NullReferenceException` in `KnightClassPerkQuadrant.OnPerkDisplaySelected`. **Every cloned asset needs a manifest entry.** Since v0.3.0, the editor adds one for each cloned asset, and for any earlier clone that lacks one. Its **Pending output** panel lists the entries before you save.

*Verified in files.* A new entry is the asset's ID plus `.asset`, under the folder spelling the manifest already uses for that asset type, such as `Assets/AssetBundles/DataAssets/ClassPerks/TechMarine_MyPerk.asset`. Bundle container paths are lowercase, but manifest paths keep the original case. *Confirmed in-game* for one perk (`Librarian_PsychicShriek_01`), inserted next to another `ClassPerks` path. The editor inserts after the first path in the same folder. *Inferred:* the position in the list doesn't matter, because the game looks paths up by name.

*Confirmed in-game.* The `hash`, `crc` and `fileSize` values aren't checked. A modified `data_assets` loads with the original values.

## Skill-tree scene (level5)

*Verified in files* unless marked. The scene MonoBehaviours here have no type trees. The layouts below come from `global-metadata.dat` field lists and were checked against all 180 branch panels and 20 trees in the scene.

### Two copies of every tree

Each knight class tree exists twice, once under `ConfigureUnitUI_Flat` and once under `ConfigureDreadnoughtUI_Flat`, both reached through `…/AbilitiesUI_Flat/Anim_Root/2D_Assets/MOUNT_AbilityPlates/AbilityTree_<Class>`. A change must be made in both copies.

### Hierarchy

```
AbilityTree_<Class>            UnitAbilityTree (script 1:1695)
├── SPT_AbilityPlate, UnitButton
└── Mounts_TopL … Mounts_BotR  9 branch groups, each with KnightClassPerkQuadrant (script 1:3225)
    ├── XX_MountN              Transform with the button position
    │   └── <perk id>          button GameObject with KnightClassPerkDisplay (script 1:302)
    │       └── 4 children     frames and icons (SpriteRenderers, Animations, collider)
    └── QuadrantSelect_NN      branch selector
```

Script references are PPtrs into external file 1, `globalgamemanagers.assets`. A button subtree has about 141 objects: Transforms, GameObjects, SpriteRenderers, 4 MonoBehaviours, Animations, a Rigidbody and a BoxCollider. Only three objects outside a subtree point into it: the parent group's `m_Children`, the branch panel's entry, and the tree's `perkDisplays` list.

### Positions

Positions are local to the parent, in world units. Branch groups sit at x ∈ {−2.9, 0, 2.9} and y ∈ {2.89, 0, −2.92}. Buttons sit about 0.96–1.0 apart (1.125 in the centre diamond). Relative to the tree root, buttons fall on a 7×7 grid: x ∈ {−2.9, −1.94, −0.98, 0, 0.98, 1.94, 2.9} and y ∈ {2.89, 1.93, 1.0, 0, −1.0, −1.92, −2.92}. Each class uses 36 of the 49 cells. The centre cell holds the middle branch selector, so 12 cells are free.

*Confirmed in-game.* A button placed off its branch's area still belongs to that branch's panel. A test Librarian perk placed at (1.01, −1.92) was parented to `Mounts_BotR` and showed in the Shriek Discipline panel. A button placed almost on top of another one wasn't visible.

### MonoBehaviour layouts

Every MonoBehaviour starts with `m_GameObject` (PPtr, 12 bytes), `m_Enabled` (4), `m_Script` (PPtr, 12) and `m_Name` (string, empty here), so fields begin at byte 32. Strings are a uint32 length followed by UTF-8 bytes, padded to 4 bytes. Booleans take 4 bytes each.

**UnitAbilityTree**: `perkDisplays` (array of PPtr<KnightClassPerkDisplay>, 36 per vanilla tree), `classButton` (PPtr). `perkToPerkDisplay` is a runtime dictionary and isn't serialised. *Confirmed in-game:* a button missing from `perkDisplays` doesn't appear.

**KnightClassPerkQuadrant** (branch panel): `title` (string, a localisation key such as `ABILITIESUI_Librarian_PerkGroupTitle_ShriekDiscipline`), `perkEntries` (array of KnightClassPerkQuadrantEntry). `selectedPerk` and `quadSelectBacker` aren't serialised.

**KnightClassPerkQuadrantEntry**, 76 bytes when all strings are empty:

| Field | Type |
|---|---|
| `displayType` | string, such as `Melee`, `ForceStrike`, `Ranged` or empty |
| `detailDisplayType` | string |
| `headerKey` | string, a section header such as `ABILITIESUI_PassiveAbility` |
| `baseEquipmentClassRef` | `{key: string}` |
| `baseAbility` | PPtr, usually to an external asset |
| `basePerk` | PPtr<KnightClassPerkDisplay>; 0 for header-only entries |
| `useAbilityAsDetail`, `doNotUseAppends` | bool, bool |
| `basePerkDisplayIcon`, `basePerkDisplayIconBacker` | PPtr, PPtr (external files) |
| `useAllLargeFrame` | bool |

**KnightClassPerkDisplay** (button): the first field `perk` is a `{key: string}` holding the perk ID. The remaining fields cover detail panels, the unowned, owned, locked and proposed-gain object lists, icons, button, knight and main UI.

## Adding a skill-tree perk

*Confirmed in-game* for display only, from the Librarian test on 2026-11-20. An extra perk appears in a tree when all of these are in place:

1. A `ClassPerksData` asset in `data_assets` with `ownerClass` set to the class and `prerequisites` linking it into the tree.
2. Its path in the `data_assets` row of `manifest.dat`.
3. In **both** scene copies: a cloned button subtree (perk ID string replaced, all internal PPtrs remapped), parented under a branch group at a free position. The button also needs an entry in that group's `perkEntries` and a place in the tree's `perkDisplays`.

The editor's **Tree layout** panel does steps 2 and 3 for you. Still not tested: spending a point to unlock an added perk, keeping it after saving and reloading, and how perk unlock levels are decided (`ClassPerksData.GetPerksForClassAtLevel` exists in code).

## Localisation keys

*Verified in files.* The text tables in `localization/english` map keys to strings.

| Asset | Keys |
|---|---|
| Perk | `CLASS_PERK_<id>_Title`, `_SubTitle`, `_Description` |
| Ability | `ABILITY_NAME_<id>`, `ABILITY_DESC_<id>`, `ABILITY_SUBTITLE_*` |
| Ability upgrade | `ABILITY_UPGRADE_DESC_<id>` |
| Weapon | `EQUIPMENT_<id>` |
| Branch panel | `ABILITIESUI_<Class>_PerkGroupTitle_<Branch>` |

*Confirmed in-game.* A cloned perk with no `CLASS_PERK_<id>_SubTitle` row shows the raw key in the details panel.

## Code patches

*Verified in files.* The method `KnightState.HandleEquipmentStealing` (token `0x0600b66b`) sits at file offset `0xfdbac0` in `GameAssembly.dll`, and patching it to return immediately allows shared special equipment. The equipment-transfer prompt branch is at `0x56b798`. `editor.py` checks the DLL hash before patching. *Confirmed in-game:* with the patch, the other knight keeps the item. The prompt bypass is untested.

Useful code addresses (virtual address / file offset): `UnitAbilityTree.Initialize` 0x180556420 / 0x555220; `UnitAbilitiesUI.DisplayPerkQuadrant` 0x180552f10 / 0x551d10; `ClassPerksData.GetPerksForClass` 0x180b46740 / 0xb45540; `ClassPerksData.GetPerksForClassAtLevel` 0x180b465e0 / 0xb453e0.

## Save files

*Inferred* from the earlier `translate.pl`. A `.gksave` file starts with a plain JSON header line (version, timestamp, location, difficulty), followed by CRLF. The body is JSON with each byte's nibbles swapped. A `0xC3` marker byte adds 4 to the next decoded byte, and a `0xC2` marker clears it. Saves store a typed record tree (`typeName` such as `GreyKnights.PlayerState`).

## Tooling notes

- UnityPy's `ObjectReader.get_raw_data()` and `read_typetree()` return the original file contents even after `set_raw_data()` or `save_typetree()`. Read edited objects from `obj.data` or your own cache.
- Each scene button is identified by its perk ID string, so clone IDs must use only letters, digits and underscores, and match `m_Name`.
