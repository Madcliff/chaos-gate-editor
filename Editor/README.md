# Chaos Gate Asset Editor

Edit classes, skill trees, abilities, upgrades, and weapons for Warhammer 40,000: Chaos Gate – Daemonhunters. The editor runs locally in your browser and reads game data and English localization from your installation.

## Quick start

Download the archive for your system from [GitHub Releases](https://github.com/Madcliff/chaos-gate-editor/releases). Extract the entire archive to a folder you can write to. Keep the bundled runtime and vendor folders together with the editor.

| Platform | Archive | Start the editor |
|---|---|---|
| Windows x64 | `windows-x64-standalone.zip` | Double-click `Editor/Start-Editor.cmd`. |
| Linux x86-64 | `linux-x86_64-standalone.zip` | Run `sh Editor/start-editor.sh` from the extracted folder. |

The standalone ZIPs include Python, UnityPy, and their required packages. You need the installed game and a browser. The older v0.1.0 Linux ZIP uses system CPython 3.14.

Keep the launcher window open while editing. Open the printed loopback URL if your browser does not open automatically. For a custom Steam library, choose the ChaosGate folder in the dialog, or launch with `--game-dir "path to ChaosGate" --save-settings`. Add `--browse` to pick a different folder. The **Paths** section shows the active game and output folders.

```bat
Editor\Start-Editor.cmd --game-dir "D:\SteamLibrary\steamapps\common\ChaosGate" --save-settings
```

```sh
sh Editor/start-editor.sh --game-dir "/games/SteamLibrary/steamapps/common/ChaosGate" --save-settings
```

Linux folder selection uses Zenity or KDialog when available. A typed path works without a picker. **Open output folder** uses Explorer on Windows and the default file manager on Linux.

## Edit a perk or ability

1. Choose **Skill trees** and pick a class. Select a perk to see its prerequisites, granted abilities, and upgrades.
2. Use the dropdowns to make changes. Perk prerequisites come from the owner class. Related fields display localized names where available.
3. Choose **Stage edit** to edit the selected perk. To make a new perk, enter a unique ID such as `MyMod_TechMarine_ExtraPerk`, then choose **Stage clone**.
4. To edit an ability, choose the corresponding ability or upgrade view. Change its fields and stage the edit or clone. To grant a staged clone, select it in the perk's ability or upgrade list.
5. Choose **Save to output folder** or **Download bundle**. Staging lasts until you reload the tab. Saving again builds from the selected game source and the edits currently staged.

**Raw JSON** exposes custom values and empty lists with no known example. Unity PathIDs are stored as strings in that view. Select an asset to see available English text, or choose **Download localization JSON** to inspect the tables. Localization preview is read-only.

### Install and undo an asset edit

Close the game. Back up `ChaosGate_Data/StreamingAssets/bundles/data_assets` from the installation, and place the exported `Editor/out/data_assets` at that path. To undo the edit, close the game and restore the backup. Test on a separate campaign save when adding new IDs. Export verifies the bundle structure. Visibility of extra perks on the promotion screen and availability of cloned weapons still require in-game testing.

## Share special weapons and armour

1. Open **Patches** and leave **Skip the equipment transfer prompt** checked if you want direct assignment. Clear it to keep the confirmation.
2. Click **Build patched GameAssembly.dll**. The editor verifies the known Steam build `0706ef9` and writes `Editor/out/shared-equipment/GameAssembly.dll`.
3. Close the game and back up its original `GameAssembly.dll` from the ChaosGate installation root. Copy the generated DLL to that location.
4. Relaunch and equip the same eligible special item on two knights. Confirm both keep it.

To undo the patch, close the game and restore the original DLL. Steam verification or an update can also replace the patched DLL. The transfer patch was observed to preserve the other knight's weapon. The prompt bypass was verified in the generated DLL and still needs in-game confirmation.

## Troubleshooting

- **Blank editor or missing assets.** Start through the launcher and open the printed HTTP address. Opening `index.html` directly cannot load the local catalog.
- **Game folder rejected.** Choose the folder containing `ChaosGate_Data`, or point directly to its `StreamingAssets/bundles` folder. Check that `data_assets` and `localization/english` are present.
- **Browser address changed.** If another program uses port 8765, the editor picks an available port. Use the address printed in the launcher window.
- **Unsupported DLL build.** The patch generator expects build `0706ef9` with the known DLL contents. Asset editing uses the installed bundles independently of DLL patch generation.
- **A staged edit disappeared.** Save or download the bundle before closing or refreshing the tab.

## License

The editor source is licensed under [GNU GPL version 2.0 only](LICENSE). Bundled dependencies and runtimes retain their upstream licenses. The archive contains the tool and runtime. It reads the game files from your installation.

## Build the release archives

From a development copy with the Linux UnityPy vendor directory, run the packaging script with the Windows x64 CPython 3.14 embeddable ZIP, the matching Windows x64 UnityPy dependency wheels, and the x86-64 GNU/Linux CPython 3.14 install-only runtime tarball. The release uses CPython 3.14.10.

```sh
python3 Editor/build_release.py --windows-runtime /path/to/python-embed.zip \
  --windows-wheels /path/to/wheels --linux-runtime /path/to/python-install-only.tar.gz
```

The Windows runtime comes from [Python.org](https://www.python.org/downloads/release/python-31410/). The Linux runtime comes from [python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20261110). Keep the upstream license files in both packages. The build script writes ZIPs and SHA-256 checksums under `dist/`.
