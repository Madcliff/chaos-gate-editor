# SPDX-License-Identifier: GPL-2.0-only
"""Local Chaos Gate asset editor."""
import argparse
from copy import copy, deepcopy
import errno
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import mmap
import os
from pathlib import Path
import re
import secrets
import platform
import sys
import shutil
import struct
import subprocess
from tempfile import NamedTemporaryFile
import webbrowser
import zipfile
from io import BytesIO

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
if VENDOR.is_dir():
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14) or (
        sys.platform, platform.machine().lower()
    ) not in {("linux", "x86_64"), ("win32", "amd64"), ("win32", "x86_64")}:
        raise SystemExit("The bundled UnityPy requires the matching x64 Windows or Linux CPython 3.14 runtime.")
    sys.path.insert(0, str(VENDOR))

import UnityPy

# The Windows embeddable runtime does not put the script folder on sys.path.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tree_layout

DEFAULT_GAME_DIR = Path.home() / ".local/share/Steam/steamapps/common/ChaosGate"
BUNDLE_SUBDIR = Path("ChaosGate_Data/StreamingAssets/bundles")
SETTINGS = ROOT / "chaos-gate.json"
OUTPUT = ROOT / "out/data_assets"
MANIFEST_OUTPUT = ROOT / "out/manifest.dat"
INSTALL_BACKUPS = ROOT / "backups"
PATCH_OUTPUT = ROOT / "out/shared-equipment/GameAssembly.dll"
# Steam build 0706ef9. The IL2CPP method table maps KnightState.HandleEquipmentStealing
# (Assembly-CSharp token 0x0600b66b) to this file offset.
EQUIPMENT_OFFSET = 0xfdbac0
LEGACY_OFFSET = 0x23FF8A
# Route the already-equipped case through the normal assignment path.
PROMPT_OFFSET = 0x56B798
PROMPT_ORIGINAL = bytes.fromhex("0F 85 3C 01 00 00")
PROMPT_SKIPPED = bytes.fromhex("90 E9 3C 01 00 00")
EQUIPMENT_BASE_HASH = "d24a4766b728dbade61381526d5ad263206f57ee3c42fc85574d8d05a1fcd183"
KINDS = {
    "ClassData", "ClassPerksData", "ActiveAbilityData", "PassiveAbilityData",
    "AutoAbilityData", "AbilityUpgradeData", "WeaponData",
}
UNITY_FIELDS = {"m_GameObject", "m_Enabled", "m_Script"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")
ABILITY_KINDS = {"ActiveAbilityData", "PassiveAbilityData", "AutoAbilityData"}


def path_ids(value, encode):
    if isinstance(value, list):
        return [path_ids(item, encode) for item in value]
    if isinstance(value, dict):
        result = {key: path_ids(item, encode) for key, item in value.items()}
        if "m_PathID" in result:
            raw = result["m_PathID"]
            if not encode and (not isinstance(raw, str) or not re.fullmatch(r"-?[0-9]+", raw)):
                raise ValueError("PathIDs must be decimal strings")
            number = int(raw)
            if not -(2**63) <= number < 2**63:
                raise ValueError("PathID out of range")
            result["m_PathID"] = str(number) if encode else number
        return result
    return value


class Bundle:
    def __init__(self, source):
        self.env = UnityPy.load(str(source))
        self.index = next(o for o in self.env.objects if o.type.name == "AssetBundle")
        self.objects = self.index.assets_file.objects
        self.records = {}
        self.reference_names = {}
        for pid, obj in self.objects.items():
            if obj.type.name != "MonoBehaviour":
                continue
            data = obj.read_typetree()
            if data.get("m_Name"):
                self.reference_names[str(pid)] = data["m_Name"]
            script = data["m_Script"]
            target = self.objects.get(script["m_PathID"]) if not script["m_FileID"] else None
            kind = target.read().m_ClassName if target and target.type.name == "MonoScript" else ""
            if kind not in KINDS:
                continue
            fields = {key: val for key, val in data.items() if key not in UNITY_FIELDS}
            self.records[str(pid)] = {"kind": kind, "data": path_ids(fields, True)}

    def validate_perks(self, changes):
        catalog = dict(self.records)
        for change in changes:
            kind = self.records[change["source"]]["kind"]
            key = ("clone", kind, change["data"]["id"]) if change["clone"] else change["source"]
            catalog[key] = {"kind": kind, "data": change["data"]}
        perks = {}
        abilities, upgrades = set(), set()
        for record in catalog.values():
            kind, data = record["kind"], record["data"]
            if kind == "ClassPerksData":
                perks[data["id"]] = data
            elif kind in ABILITY_KINDS:
                abilities.add(data["id"])
            elif kind == "AbilityUpgradeData":
                upgrades.add(data["id"])
        for change in changes:
            original = self.records[change["source"]]
            if original["kind"] != "ClassPerksData":
                continue
            data = change["data"]
            owner = data["ownerClass"]
            prior = {} if change["clone"] else original["data"]
            if owner != prior.get("ownerClass"):
                target = self.records.get(owner["m_PathID"])
                if owner["m_FileID"] or not target or target["kind"] != "ClassData":
                    raise ValueError(f'{data["id"]} needs a valid owner class')
            for field, targets in (("prerequisites", perks), ("abilities", abilities), ("upgrades", upgrades)):
                old_keys = {item["key"] for item in prior.get(field, [])}
                for item in data[field]:
                    key = item["key"]
                    if key in old_keys and owner == prior.get("ownerClass"):
                        continue
                    if key not in targets or (field == "prerequisites" and perks[key]["ownerClass"] != owner):
                        raise ValueError(f'{data["id"]} has an invalid {field} reference: {key}')
            if data["prerequisites"] != prior.get("prerequisites"):
                seen = set()
                pending = [item["key"] for item in data["prerequisites"]]
                while pending:
                    key = pending.pop()
                    if key == data["id"]:
                        raise ValueError(f'Prerequisite cycle involving {key}')
                    if key in perks and key not in seen:
                        seen.add(key)
                        pending.extend(item["key"] for item in perks[key]["prerequisites"])

    def export(self, changes):
        if not isinstance(changes, list):
            raise ValueError("Expected a list of changes")
        index = self.index.read_typetree()
        container = index["m_Container"]
        entries = {v["asset"]["m_PathID"]: (k, v) for k, v in container if not v["asset"]["m_FileID"]}
        paths = {key.casefold() for key, _ in container}
        names = {(r["kind"], r["data"].get("id", r["data"]["m_Name"]).casefold())
                 for r in self.records.values()}
        edited = set()
        expected = {}
        self.added_paths = []
        for change in changes:
            source = change["source"]
            original = self.records[source]
            if not isinstance(change["clone"], bool):
                raise ValueError("Invalid clone flag")
            clone = change["clone"]
            fields = change["data"]
            before = original["data"]
            if set(fields) != set(before):
                raise ValueError("Keep the original asset fields")
            reader = self.objects[int(source)]
            full = reader.read_typetree()
            if clone:
                name = fields.get("id")
                if original["kind"] == "ClassData" or not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
                    raise ValueError("Clones require an ID containing only letters, digits and underscores")
                identity = (original["kind"], name.casefold())
                if identity in names or fields["m_Name"] != name:
                    raise ValueError("A clone needs a unique ID and a matching m_Name")
                names.add(identity)
                template_path, template = entries[int(source)]
                prefix = template_path.rsplit("/", 1)[0]
                path = f"{prefix}/{name.lower()}.asset"
                if path in paths:
                    raise ValueError(f"Bundle path already exists for {name}")
                paths.add(path)
                self.added_paths.append((path, name))
                pid = int.from_bytes(sha256(path.encode()).digest()[:8], "big") & (2**63 - 1)
                if not pid or pid in self.objects:
                    raise ValueError(f"PathID collision for {name}. Choose a different ID.")
                reader = copy(reader)
                reader.path_id = pid
                self.objects[pid] = reader
                entry = deepcopy(template)
                entry["asset"]["m_PathID"] = pid
                preload = index["m_PreloadTable"]
                start = template["preloadIndex"]
                deps = deepcopy(preload[start:start + template["preloadSize"]])
                for dep in deps:
                    if dep == {"m_FileID": 0, "m_PathID": int(source)}:
                        dep["m_PathID"] = pid
                entry["preloadIndex"] = len(preload)
                preload.extend(deps)
                container.append((path, entry))
            else:
                if source in edited or any(fields.get(key) != before.get(key) for key in ("id", "m_Name")):
                    raise ValueError("Existing asset IDs and names are fixed")
                edited.add(source)
            decoded = path_ids(fields, False)
            full.update(decoded)
            reader.save_typetree(full)
            expected[reader.path_id] = full

        self.validate_perks(changes)
        self.final_perks = {}
        for record in self.records.values():
            if record["kind"] == "ClassPerksData":
                self.final_perks[record["data"]["id"]] = record["data"]["ownerClass"]["m_PathID"]
        for change in changes:
            if self.records[change["source"]]["kind"] == "ClassPerksData":
                self.final_perks[change["data"]["id"]] = change["data"]["ownerClass"]["m_PathID"]
        if any(c["clone"] for c in changes):
            container.sort(key=lambda item: item[0])
            self.index.save_typetree(index)
        bundle = next(iter(self.env.files.values())).save(packer="original")
        reopened = UnityPy.load(bundle)
        index_check = next(o for o in reopened.objects if o.type.name == "AssetBundle")
        if index_check.read_typetree() != index:
            raise ValueError("Bundle index failed round-trip verification")
        for pid, data in expected.items():
            if index_check.assets_file.objects[pid].read_typetree() != data:
                raise ValueError(f"Asset {pid} failed round-trip verification")
        return bundle


def manifest_additions(bundle, clones=None):
    """List (container path, asset name) for every data asset, including new clones.

    clones lists (source PathID, new ID) for staged clones not yet exported; by
    default the clones recorded by the last export are used.
    """
    index = bundle.index.read_typetree()
    names = dict(bundle.reference_names)
    pending = [(path, name) for path, name in getattr(bundle, "added_paths", [])]
    entries = {}
    for path, entry in index["m_Container"]:
        asset = entry["asset"]
        if not asset["m_FileID"]:
            entries[str(asset["m_PathID"])] = path
            if str(asset["m_PathID"]) in names:
                pending.append((path, names[str(asset["m_PathID"])]))
    for source, name in clones or []:
        template = entries.get(str(source))
        if template:
            pending.append((f'{template.rsplit("/", 1)[0]}/{name.lower()}.asset', name))
    return pending


def plan_outputs(bundle, manifest_path, payload):
    """Describe what a save would write, without building anything."""
    if isinstance(payload, list):
        payload = {"changes": payload, "placements": []}
    changes = payload.get("changes", []) if isinstance(payload, dict) else []
    placements = payload.get("placements", []) if isinstance(payload, dict) else []
    if not isinstance(changes, list) or not isinstance(placements, list):
        raise ValueError("Expected staged changes and tree placements")
    clones = [(c["source"], c["data"]["id"]) for c in changes
              if isinstance(c, dict) and c.get("clone") and isinstance(c.get("data"), dict)
              and isinstance(c["data"].get("id"), str)]
    manifest = []
    if manifest_path.is_file():
        _, manifest = tree_layout.add_manifest_paths(manifest_path.read_bytes(),
                                                     manifest_additions(bundle, clones))
    return {"data": len(changes), "manifest": manifest,
            "scene": [f'{p.get("perk")} → {p.get("class")} / {p.get("group")} at ({p.get("x")}, {p.get("y")})'
                      for p in placements if isinstance(p, dict)]}


class Outputs(dict):
    added_manifest = ()


def build_outputs(source, scene_path, payload):
    """Build the data bundle and, when needed, manifest.dat and the tree scene.

    Returns {filename: bytes} for each file that differs from the installed game.
    """
    if isinstance(payload, list):
        payload = {"changes": payload, "placements": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list) \
            or not isinstance(payload.get("placements", []), list):
        raise ValueError("Expected staged changes and tree placements")
    changes, placements = payload["changes"], payload.get("placements", [])
    bundle = Bundle(source)
    outputs = Outputs(data_assets=bundle.export(changes))
    manifest_path = source.parent / "manifest.dat"
    if manifest_path.is_file():
        manifest = manifest_path.read_bytes()
        updated, added = tree_layout.add_manifest_paths(manifest, manifest_additions(bundle))
        if updated != manifest:
            outputs["manifest.dat"] = updated
            outputs.added_manifest = added
    elif any(change.get("clone") for change in changes):
        raise ValueError(f"Cloned assets need manifest.dat, which was not found at {manifest_path}")
    if placements:
        if not scene_path:
            raise ValueError("The skill-tree scene was not found in this installation")
        classes = {pid: r["data"]["m_Name"] for pid, r in bundle.records.items() if r["kind"] == "ClassData"}
        scene = tree_layout.TreeScene(scene_path)
        written = {}
        for placement in placements:
            if not isinstance(placement, dict):
                raise ValueError("Invalid tree placement")
            perk, class_name = placement.get("perk"), placement.get("class")
            owner = bundle.final_perks.get(perk)
            if owner is None:
                raise ValueError(f"Tree placement {perk} has no matching perk asset")
            if classes.get(owner) != class_name:
                raise ValueError(f"{perk} belongs to {classes.get(owner, 'another class')}, not {class_name}")
            x, y = placement.get("x"), placement.get("y")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
                raise ValueError(f"Invalid position for {perk}")
            written.update(scene.add_node(class_name, perk, placement.get("template"),
                                          placement.get("group"), float(x), float(y)))
        outputs[scene_path.name] = scene.save(written)
    return outputs


def output_files(outputs):
    """Write outputs to the output folder and clear stale ones from earlier saves."""
    folder = OUTPUT.parent
    for stale in (folder / "manifest.dat", *folder.glob("level[0-9]*")):
        if stale.is_file() and stale.name not in outputs:
            stale.unlink()
    for filename, content in outputs.items():
        write_atomic(folder / filename, content)
    return [str(folder / filename) for filename in outputs]


def game_running():
    if sys.platform == "win32":
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ChaosGate.exe", "/NH"],
                                capture_output=True, text=True)
        return "chaosgate.exe" in result.stdout.lower()
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if any(arg.replace(b"\\", b"/").rsplit(b"/", 1)[-1].lower() == b"chaosgate.exe" for arg in args):
            return True
    return False


def install_targets(source, scene_path):
    targets = {"data_assets": source, "manifest.dat": source.parent / "manifest.dat"}
    if scene_path:
        targets[scene_path.name] = scene_path
    return targets


def install_outputs(source, scene_path):
    """Copy saved outputs into the game, backing up each original once."""
    if game_running():
        raise ValueError("Close Chaos Gate before installing.")
    folder = OUTPUT.parent
    installed = []
    for filename, target in install_targets(source, scene_path).items():
        output = folder / filename
        if not output.is_file():
            continue
        backup = INSTALL_BACKUPS / filename
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        if target.read_bytes() != output.read_bytes():
            write_atomic(target, output.read_bytes())
            installed.append(filename)
    if not installed:
        return "The game already matches the saved output. Save to output folder first."
    return f"Installed {', '.join(installed)}. Originals are kept in {INSTALL_BACKUPS}. Restart the editor to edit the installed files."


def restore_originals(source, scene_path):
    if game_running():
        raise ValueError("Close Chaos Gate before restoring.")
    restored = []
    for filename, target in install_targets(source, scene_path).items():
        backup = INSTALL_BACKUPS / filename
        if backup.is_file() and backup.read_bytes() != target.read_bytes():
            write_atomic(target, backup.read_bytes())
            restored.append(filename)
    if not restored:
        return "No backups differ from the installed files."
    return f"Restored {', '.join(restored)} from {INSTALL_BACKUPS}. Restart the editor to reload them."


def read_localization(source):
    rows = []
    for obj in UnityPy.load(str(source)).objects:
        if obj.type.name != "MonoBehaviour":
            continue
        table = obj.read_typetree()
        rows.extend({"table": table["m_Name"], **row} for row in table.get("localizationData", []))
    return rows


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.close()
            if path.exists():
                pending.chmod(path.stat().st_mode & 0o777)
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def show_url(port, open_browser, existing=False):
    url = f"http://127.0.0.1:{port}/"
    print(f"{'Editor already running. ' if existing else ''}Open {url}", flush=True)
    if open_browser:
        webbrowser.open(url)


def patch_shared_equipment(assembly, output, skip_prompt=False):
    if not assembly.is_file():
        raise ValueError(f"GameAssembly.dll was not found at {assembly}")
    if assembly.resolve() == output.resolve():
        raise ValueError("Choose an output folder outside the game installation")
    with assembly.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if len(data) <= EQUIPMENT_OFFSET:
            raise ValueError("Unsupported GameAssembly.dll build")
        patches = (
            (LEGACY_OFFSET, b"\x74", b"\xeb", b"\x74"),
            (PROMPT_OFFSET, PROMPT_ORIGINAL, PROMPT_SKIPPED,
             PROMPT_SKIPPED if skip_prompt else PROMPT_ORIGINAL),
            (EQUIPMENT_OFFSET, b"\x48", b"\xc3", b"\xc3"),
        )
        digest = sha256()
        start = 0
        replacements = {}
        for offset, original, alternate, desired in patches:
            current = data[offset:offset + len(original)]
            if current not in (original, alternate):
                raise ValueError("Unsupported GameAssembly.dll build")
            digest.update(memoryview(data)[start:offset])
            digest.update(original)
            start = offset + len(original)
            if current != desired:
                replacements[offset] = desired
        digest.update(memoryview(data)[start:])
        if digest.hexdigest() != EQUIPMENT_BASE_HASH:
            raise ValueError("Shared equipment supports the known Steam build 0706ef9.")
        if not replacements:
            return f"The selected patch options are already enabled in {assembly}"
        output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
            pending = Path(temporary.name)
            try:
                def chunks():
                    for start in range(0, len(data), 8 * 1024 * 1024):
                        block = data[start:start + 8 * 1024 * 1024]
                        for position, opcodes in replacements.items():
                            offset = position - start
                            if 0 <= offset < len(block):
                                block = block[:offset] + opcodes + block[offset + len(opcodes):]
                        yield block

                for block in chunks():
                    temporary.write(block)
                temporary.seek(0)
                for block in chunks():
                    if temporary.read(len(block)) != block:
                        raise OSError("Patched DLL failed verification")
                temporary.close()
                pending.replace(output)
            finally:
                pending.unlink(missing_ok=True)
    return f"Saved verified patched DLL to {output}"


def serve(source, port, localization, open_browser=False):
    database = Bundle(source)
    records = database.records
    token = secrets.token_urlsafe()
    rows = read_localization(localization)
    translations = {row["id"]: row["translation"] for row in rows}
    scene_path, trees, tree_error = None, {}, ""
    data_dir = source.parent.parent.parent
    if (source.parent.parent / "bundles") == source.parent and data_dir.is_dir():
        scene_path = tree_layout.find_scene(data_dir)
    try:
        trees = tree_layout.TreeScene(scene_path).summary() if scene_path else {}
    except (ValueError, KeyError, struct.error) as error:
        scene_path, tree_error = None, f"Skill-tree layout unavailable: {error}"
    catalog = json.dumps({"records": records, "token": token, "translations": translations,
                          "referenceNames": database.reference_names, "trees": trees, "treeError": tree_error,
                          "paths": {"game": str(source.parent), "output": str(OUTPUT.parent),
                                    "scene": str(scene_path or ""), "backups": str(INSTALL_BACKUPS)}}).encode()
    localization_json = json.dumps(rows, ensure_ascii=False, indent=2).encode()
    bundles = source.parent
    assembly = bundles / "GameAssembly.dll"
    if len(bundles.parents) >= 3 and bundles.relative_to(bundles.parents[2]) == BUNDLE_SUBDIR:
        assembly = bundles.parents[2] / "GameAssembly.dll"

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, content_type, filename=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/health":
                health = {"editor": "chaos-gate", "source": str(source)}
                self.reply(200, json.dumps(health).encode(), "application/json")
            elif self.path == "/catalog":
                self.reply(200, catalog, "application/json")
            elif self.path == "/localization.json" and rows:
                self.reply(200, localization_json, "application/json", "localization.json")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path not in {"/export", "/apply", "/patch/shared-equipment", "/open-output",
                                 "/install", "/restore", "/plan"}:
                self.send_error(404)
                return
            if self.headers.get("X-Editor-Token") != token:
                self.send_error(403)
                return
            try:
                if self.path == "/open-output":
                    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                    if sys.platform == "win32":
                        os.startfile(OUTPUT.parent)
                    else:
                        opener = shutil.which("xdg-open")
                        if not opener:
                            raise ValueError(f"Open {OUTPUT.parent} in your file manager.")
                        subprocess.Popen([opener, str(OUTPUT.parent)], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
                    self.reply(200, b"Opened output folder", "text/plain; charset=utf-8")
                    return
                if self.path == "/plan":
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 8_000_000:
                        raise ValueError("Invalid plan size")
                    plan = plan_outputs(database, source.parent / "manifest.dat", json.loads(self.rfile.read(size)))
                    self.reply(200, json.dumps(plan).encode(), "application/json")
                    return
                if self.path in {"/install", "/restore"}:
                    action = install_outputs if self.path == "/install" else restore_originals
                    self.reply(200, action(source, scene_path).encode(), "text/plain; charset=utf-8")
                    return
                if self.path == "/patch/shared-equipment":
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= size <= 1024:
                        raise ValueError("Invalid patch settings size")
                    options = json.loads(self.rfile.read(size)) if size else {}
                    if not isinstance(options, dict) or type(options.get("skipPrompt", False)) is not bool:
                        raise ValueError("Invalid prompt preference")
                    message = patch_shared_equipment(assembly, PATCH_OUTPUT, options.get("skipPrompt", False))
                    self.reply(200, message.encode(), "text/plain; charset=utf-8")
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8_000_000:
                    raise ValueError("Invalid export size")
                outputs = build_outputs(source, scene_path, json.loads(self.rfile.read(size)))
                if self.path == "/apply":
                    if OUTPUT.parent.resolve() == source.parent.resolve():
                        raise ValueError("Output points to the game folder. Use Download instead.")
                    written = output_files(outputs)
                    message = "Saved verified files:\n" + "\n".join(written)
                    if outputs.added_manifest:
                        message += "\n\nmanifest.dat entries added:\n" + "\n".join(outputs.added_manifest)
                    self.reply(200, message.encode(), "text/plain; charset=utf-8")
                    return
            except Exception as exc:
                self.reply(400, str(exc).encode(), "text/plain; charset=utf-8")
                return
            if len(outputs) == 1:
                self.reply(200, outputs["data_assets"], "application/octet-stream", "data_assets")
                return
            archive = BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
                for filename, content in outputs.items():
                    package.writestr(filename, content)
            self.reply(200, archive.getvalue(), "application/zip", "chaos-gate-mod.zip")

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        show_url(server.server_port, open_browser)
        server.serve_forever()


def game_files(directory):
    directory = directory.expanduser().resolve()
    for bundles in (directory / BUNDLE_SUBDIR, directory):
        source = bundles / "data_assets"
        localization = bundles / "localization/english"
        if source.is_file() and localization.is_file():
            return source, localization
    raise ValueError(f"Could not find data_assets and localization/english under {directory}. "
                     "Set --game-dir to the ChaosGate install folder or its bundles folder.")


def discover_game_dir():
    if sys.platform == "win32":
        import winreg

        steam_roots = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"]
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_roots.insert(0, Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        steam_paths = [root / "steamapps/common/ChaosGate" for root in steam_roots]
    else:
        steam_paths = (
            DEFAULT_GAME_DIR,
            Path.home() / ".steam/steam/steamapps/common/ChaosGate",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/ChaosGate",
        )
    return next((path for path in steam_paths if (path / BUNDLE_SUBDIR / "data_assets").is_file()), None)


def choose_game_dir(start):
    if sys.platform == "win32":
        script = """
            [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
            Add-Type -AssemblyName System.Windows.Forms
            $picker = New-Object System.Windows.Forms.FolderBrowserDialog
            $picker.Description = 'Choose the ChaosGate game folder'
            $picker.SelectedPath = $env:CHAOS_GATE_PICKER_START
            if ($picker.ShowDialog() -eq 'OK') { [Console]::Write($picker.SelectedPath) }
            else { exit 1 }
        """
        env = dict(os.environ, CHAOS_GATE_PICKER_START=str(start))
        command = ["powershell.exe", "-NoProfile", "-STA", "-Command", script]
        result = subprocess.run(command, capture_output=True, encoding="utf-8", env=env)
        if result.returncode or not result.stdout:
            raise ValueError("No game folder selected. Use --game-dir to enter the path.")
        return Path(result.stdout.strip())
    if shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", "--title=Choose the ChaosGate game folder",
                   "--filename=" + str(start) + "/"]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", str(start), "--title", "Choose the ChaosGate game folder"]
    else:
        raise ValueError("No desktop folder picker is available. Use --game-dir to enter the path.")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("No game folder selected. Use --game-dir to enter the path.")
    return Path(result.stdout.strip())


def running_editor(port):
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        if response.status == 200:
            health = json.loads(response.read(4096))
            if isinstance(health, dict) and health.get("editor") == "chaos-gate":
                return health["source"]
    except (OSError, HTTPException, ValueError, KeyError):
        pass
    finally:
        connection.close()
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path,
                        help="ChaosGate install or bundles directory (also CHAOS_GATE_GAME_DIR)")
    parser.add_argument("--port", type=int, help="Preferred port (default 8765)")
    parser.add_argument("--browse", action="store_true", help="Choose and remember the game folder in a desktop dialog")
    parser.add_argument("--save-settings", action="store_true", help="Remember the selected game path")
    parser.add_argument("--no-browser", action="store_true", help="Print the address without opening a browser")
    args = parser.parse_args()
    try:
        directory = args.game_dir or os.environ.get("CHAOS_GATE_GAME_DIR")
        if not directory and SETTINGS.is_file():
            directory = json.loads(SETTINGS.read_text())["game_dir"]
        directory = directory or discover_game_dir()
        if args.browse or (not directory and not args.no_browser and
                           (sys.platform == "win32" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))):
            directory = choose_game_dir(Path(directory or Path.home()).expanduser())
            args.save_settings = True
        directory = Path(directory or DEFAULT_GAME_DIR).expanduser().resolve()
        source, localization = game_files(directory)
        if args.save_settings:
            write_atomic(SETTINGS, json.dumps({"game_dir": str(directory)}, indent=2).encode())
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    port = args.port if args.port is not None else 8765
    try:
        try:
            serve(source, port, localization, not args.no_browser)
        except OSError as error:
            if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
                raise
            existing = running_editor(port)
            if existing == str(source):
                show_url(port, not args.no_browser, existing=True)
            elif args.port is None:
                serve(source, 0, localization, not args.no_browser)
            else:
                parser.exit(1, f"Port {port} is in use. Choose a free port or omit --port.\n")
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        parser.exit(1, f"Could not start the editor: {error}\n")
