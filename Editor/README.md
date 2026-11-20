# Chaos Gate Asset Editor

Start the editor from the project directory.

```sh
python3 Editor/editor.py
```

The editor opens the browser automatically. If another program uses its default port, it picks a free one and prints the address. Use `--no-browser` to print the address only. The editor reads `data_assets` and `localization/english` directly from the standard Linux Steam installation. UnityPy 1.25.4 and its dependencies are bundled in the editor’s `vendor` directory. Keep that directory beside `editor.py`. This build uses CPython 3.14 on x86-64 Linux.

For a different installation, pass its directory.

```sh
python3 Editor/editor.py --game-dir "/path/to/ChaosGate" --save-settings
```

You can also point to the `bundles` directory directly, or set `CHAOS_GATE_GAME_DIR` in your shell to reuse a directory across launches.

1. Choose **Skill trees**, select a class, and click a perk. The columns group perks by prerequisite depth.
2. Edit the perk's prerequisites, granted abilities, and upgrades by ID. Use the editable fields for other properties. Expand **Raw JSON** when you need to edit the serialized data directly.
3. Click **Stage edit** to queue a change. To add a perk, enter a new asset ID and click **Stage clone**. Select the staged clone in the tree to revise it.
4. Click **Save to output folder** to write all staged changes to `Editor/out/data_assets`, or **Download bundle** for a browser download. Saving again replaces the output with the current staged changes applied to the source. Staging lasts until the page reloads.

The other asset views let you edit class, ability, upgrade, and weapon fields. Ability and weapon records can also be cloned. Clone IDs need separate localization entries if the game looks up their display text by ID.

The exporter reopens the generated bundle to verify its index and changed assets. The game files are read-only inputs. Game installation and in-game testing are separate steps. In particular, an exported perk beyond the base tree still needs to be tested on the promotion screen, and cloned weapons still need to be tested for availability.

Select an asset to see matching localization keys and text, or click **Download localization JSON** to extract the English tables from the selected game directory.

Asset references and fields with known game values use dropdowns. Perk prerequisites are scoped to the selected owner class. The editor uses translated names where available and retains internal IDs in the option labels. Lists with an example in the game data can be started from the form. Raw JSON remains available for fields without an example and for custom values.

Open **Patches** and choose **Build patched GameAssembly.dll** to enable shared special equipment. The editor checks the Steam build 0706ef9 DLL against the known original and writes a verified copy to `Editor/out/shared-equipment/GameAssembly.dll`. It reports when the source already contains the patch.

## Paths and folder picker

On launch the editor checks common Linux Steam install paths, including Flatpak Steam. Run `python3 Editor/editor.py --browse` to choose a folder and remember it in `Editor/chaos-gate.json`. The picker uses Zenity or KDialog when available. **Paths** in the editor shows the active bundle and output folders and opens the output in your file manager using `xdg-open`.

## Shared equipment patch

**Skip the equipment transfer prompt** is checked by default. With it enabled, selecting eligible gear already equipped by another knight takes the regular assignment path. The shared-equipment patch suppresses the transfer that would remove gear from the first knight. Clear the checkbox if you want to keep the prompt.

To install, close the game, back up the original `GameAssembly.dll`, then copy the generated DLL into the game directory. To revert, close the game and restore that backup. Patch generation supports the verified Steam build `0706ef9`. Check that both knights retain the same gear when you select it in-game.

## Release archive

Extract the ZIP and keep the `Editor` directory intact. It contains the editor, UnityPy and its bundled dependencies, and their upstream notices in `Editor/vendor`. The archive uses CPython 3.14 on x86-64 Linux. It reads the asset and English localization bundles from your installation. The optional FMOD audio runtime is outside the scope of the editor and excluded from the archive.

## License

The editor source is licensed under GNU GPL version 2.0 only. See [LICENSE](LICENSE). Bundled dependencies retain their upstream licenses and notices in `vendor`.
