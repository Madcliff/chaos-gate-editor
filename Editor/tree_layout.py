# SPDX-License-Identifier: GPL-2.0-only
"""Read and extend the knight skill-tree buttons in the promotion scene.

Each knight class tree exists twice in the scene (ConfigureUnitUI and
ConfigureDreadnoughtUI). A tree root ``AbilityTree_<Class>`` holds nine
``Mounts_*`` groups. Each group holds mount transforms, and each mount holds one
perk button whose KnightClassPerkDisplay names the perk ID. The group's
KnightClassPerkQuadrant lists the buttons shown in that branch's panel, and the
tree's UnitAbilityTree lists every button.

These MonoBehaviours have no type trees in the scene, so their layouts come from
the IL2CPP field metadata of Steam build 0706ef9 and are validated on load.
"""
from copy import copy, deepcopy
import mmap
import re
import struct

import UnityPy

# MonoScript PathIDs in globalgamemanagers.assets (external file 1).
TREE_SCRIPT = (1, 1695)       # UnitAbilityTree
QUADRANT_SCRIPT = (1, 3225)   # KnightClassPerkQuadrant
DISPLAY_SCRIPT = (1, 302)     # KnightClassPerkDisplay
SCRIPT_OFFSET = 16
FIELDS_OFFSET = 32            # after m_GameObject, m_Enabled, m_Script, empty m_Name

# Node grid relative to the tree root: three columns per side group and the centre.
GRID_X = (-2.9, -1.94, -0.98, 0.0, 0.98, 1.94, 2.9)
GRID_Y = (2.89, 1.93, 1.0, 0.0, -1.0, -1.92, -2.92)
OCCUPIED_RADIUS = 0.45
IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")


def _pointer(pid):
    return struct.pack("<iq", 0, pid)


def _string(raw, offset):
    length, = struct.unpack_from("<I", raw, offset)
    if length > len(raw) - offset - 4:
        raise ValueError("Unexpected scene layout")
    end = offset + 4 + length
    return raw[offset + 4:end].decode("utf-8"), end + (-length % 4)


def _encode_string(text):
    data = text.encode("utf-8")
    return struct.pack("<I", len(data)) + data + b"\0" * (-len(data) % 4)


def _script(raw):
    return struct.unpack_from("<iq", raw, SCRIPT_OFFSET) if len(raw) >= 28 else None


def _game_object(raw):
    return struct.unpack_from("<q", raw, 4)[0]


def parse_quadrant(raw):
    """Return (title, entries) where each entry is (start, end, basePerk PathID)."""
    title, offset = _string(raw, FIELDS_OFFSET)
    count, = struct.unpack_from("<I", raw, offset)
    offset += 4
    entries = []
    for _ in range(count):
        start = offset
        for _ in range(4):  # displayType, detailDisplayType, headerKey, baseEquipmentClassRef.key
            _, offset = _string(raw, offset)
        offset += 12  # baseAbility PPtr
        file_id, perk = struct.unpack_from("<iq", raw, offset)
        offset += 12 + 8 + 12 + 12 + 4  # basePerk, two bools, icon, backer, useAllLargeFrame
        if file_id:
            raise ValueError("Unexpected perk reference in quadrant")
        entries.append((start, offset, perk))
    if offset != len(raw):
        raise ValueError("Quadrant layout does not match build 0706ef9")
    return title, entries


def parse_tree(raw):
    count, = struct.unpack_from("<I", raw, FIELDS_OFFSET)
    end = FIELDS_OFFSET + 4 + 12 * count
    displays = [struct.unpack_from("<iq", raw, FIELDS_OFFSET + 4 + 12 * i) for i in range(count)]
    if any(file_id for file_id, _ in displays) or len(raw) != end + 12:
        raise ValueError("Tree layout does not match build 0706ef9")
    return [pid for _, pid in displays], end


def find_scene(data_dir):
    """Locate the scene file holding the knight ability trees."""
    for path in sorted(data_dir.glob("level[0-9]*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 99):
        if not path.name[5:].isdigit() or not path.is_file():
            continue
        with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data.find(b"AbilityTree_Librarian") != -1:
                return path
    return None


class TreeScene:
    def __init__(self, source):
        self.env = UnityPy.load(source if isinstance(source, bytes) else str(source))
        self.scene = next(iter(self.env.files.values()))
        self.objects = self.scene.objects
        self._edited_trees = {}
        self.trees = {}  # class name -> list of tree instances
        for obj in list(self.objects.values()):
            if obj.type.name != "MonoBehaviour":
                continue
            raw = obj.get_raw_data()
            if _script(raw) == TREE_SCRIPT:
                instance = self._read_tree(obj.path_id, raw)
                self.trees.setdefault(instance["class"], []).append(instance)
        if not self.trees:
            raise ValueError("No knight ability trees were found in the scene")

    def _typetree(self, pid):
        if pid in self._edited_trees:
            return deepcopy(self._edited_trees[pid])
        return self.objects[pid].read_typetree()

    def _raw(self, pid):
        obj = self.objects[pid]
        return obj.data if obj.data is not None else obj.get_raw_data()

    def _save_typetree(self, pid, data):
        self._edited_trees[pid] = deepcopy(data)
        return self.objects[pid].save_typetree(data)

    def _name(self, game_object):
        return self._typetree(game_object)["m_Name"]

    def _transform(self, game_object):
        return self._typetree(game_object)["m_Component"][0]["component"]["m_PathID"]

    def _read_tree(self, tree_id, raw):
        root_object = _game_object(raw)
        name = self._name(root_object)
        if not name.startswith("AbilityTree_"):
            raise ValueError(f"Unexpected tree object {name}")
        root = self._transform(root_object)
        displays, _ = parse_tree(raw)
        groups, nodes = {}, []
        for child in self._typetree(root)["m_Children"]:
            transform = self._typetree(child["m_PathID"])
            group_object = transform["m_GameObject"]["m_PathID"]
            group_name = self._name(group_object)
            if not group_name.startswith("Mounts_"):
                continue
            quadrant = None
            for component in self._typetree(group_object)["m_Component"]:
                pid = component["component"]["m_PathID"]
                if self.objects[pid].type.name == "MonoBehaviour" and _script(self._raw(pid)) == QUADRANT_SCRIPT:
                    quadrant = pid
            if quadrant is None:
                raise ValueError(f"{name}/{group_name} has no branch panel")
            title, _ = parse_quadrant(self._raw(quadrant))
            position = transform["m_LocalPosition"]
            groups[group_name] = {"name": group_name, "title": title, "transform": child["m_PathID"],
                                  "quadrant": quadrant, "x": position["x"], "y": position["y"],
                                  "selectors": []}
        for display in displays:
            display_raw = self._raw(display)
            if _script(display_raw) != DISPLAY_SCRIPT:
                raise ValueError("Unexpected perk button script")
            perk, _ = _string(display_raw, FIELDS_OFFSET)
            button = self._typetree(self._transform(_game_object(display_raw)))
            mount = button["m_Father"]["m_PathID"]
            mount_data = self._typetree(mount)
            group_transform = mount_data["m_Father"]["m_PathID"]
            group = next((g for g in groups.values() if g["transform"] == group_transform), None)
            if group is None:
                raise ValueError(f"Perk button {perk} sits outside a branch group")
            local = mount_data["m_LocalPosition"]
            nodes.append({"perk": perk, "group": group["name"], "display": display, "mount": mount,
                          "x": round(group["x"] + local["x"], 3), "y": round(group["y"] + local["y"], 3)})
        for group in groups.values():
            for child in self._typetree(group["transform"])["m_Children"]:
                data = self._typetree(child["m_PathID"])
                if self._name(data["m_GameObject"]["m_PathID"]).startswith("QuadrantSelect"):
                    local = data["m_LocalPosition"]
                    group["selectors"].append((group["x"] + local["x"], group["y"] + local["y"]))
        return {"class": name[len("AbilityTree_"):], "tree": tree_id, "groups": groups, "nodes": nodes}

    def summary(self):
        """Describe each class tree for the editor UI, using its first instance."""
        result = {}
        for name, instances in sorted(self.trees.items()):
            first = instances[0]
            perks = sorted(n["perk"] for n in first["nodes"])
            consistent = all(sorted(n["perk"] for n in i["nodes"]) == perks for i in instances)
            blocked = [(n["x"], n["y"]) for n in first["nodes"]]
            blocked += [s for g in first["groups"].values() for s in g["selectors"]]
            cells = []
            for y in GRID_Y:
                for x in GRID_X:
                    taken = any(abs(x - bx) <= OCCUPIED_RADIUS and abs(y - by) <= OCCUPIED_RADIUS for bx, by in blocked)
                    cells.append({"x": x, "y": y, "free": not taken, "group": self.nearest_group(first, x, y)})
            result[name] = {
                "instances": len(instances),
                "consistent": consistent,
                "groups": [{k: g[k] for k in ("name", "title", "x", "y")} for g in first["groups"].values()],
                "nodes": [{k: n[k] for k in ("perk", "group", "x", "y")} for n in first["nodes"]],
                "cells": cells,
            }
        return result

    @staticmethod
    def nearest_group(tree, x, y):
        return min(tree["groups"].values(), key=lambda g: (max(abs(g["x"] - x), abs(g["y"] - y)),
                                                          abs(g["x"] - x) + abs(g["y"] - y)))["name"]

    # ----- editing -------------------------------------------------------

    def _collect(self, transform, ids):
        data = self._typetree(transform)
        game_object = data["m_GameObject"]["m_PathID"]
        ids.update((transform, game_object))
        ids.update(c["component"]["m_PathID"] for c in self._typetree(game_object)["m_Component"])
        for child in data["m_Children"]:
            if child["m_FileID"]:
                raise ValueError("Unexpected external child transform")
            self._collect(child["m_PathID"], ids)

    @staticmethod
    def _translate(value, mapping):
        if isinstance(value, dict):
            if value.get("m_FileID") == 0 and value.get("m_PathID") in mapping:
                return {"m_FileID": 0, "m_PathID": mapping[value["m_PathID"]]}
            return {k: TreeScene._translate(v, mapping) for k, v in value.items()}
        if isinstance(value, list):
            return [TreeScene._translate(v, mapping) for v in value]
        return value

    def add_node(self, class_name, perk, template, group_name, x, y):
        """Clone the template perk's button into every instance of a class tree."""
        if not IDENTIFIER.fullmatch(perk):
            raise ValueError(f"Invalid perk ID {perk}")
        instances = self.trees.get(class_name)
        if not instances:
            raise ValueError(f"No skill tree for class {class_name}")
        if not all(-4.5 <= v <= 4.5 for v in (x, y)):
            raise ValueError("Tree positions must stay within ±4.5 of the centre")
        written = {}
        for tree in instances:
            if any(n["perk"] == perk for n in tree["nodes"]):
                raise ValueError(f"{perk} already has a button in the {class_name} tree")
            source = next((n for n in tree["nodes"] if n["perk"] == template), None)
            group = tree["groups"].get(group_name)
            if source is None or group is None:
                raise ValueError(f"Choose a template perk and branch from the {class_name} tree")
            ids = set()
            self._collect(source["mount"], ids)
            mount_object = self._typetree(source["mount"])["m_GameObject"]["m_PathID"]
            next_id = max(self.objects) + 1
            mapping = {old: next_id + index for index, old in enumerate(sorted(ids))}
            for old, new in mapping.items():
                original = self.objects[old]
                clone = copy(original)
                clone.path_id = new
                self.objects[new] = clone
                if original.type.name == "MonoBehaviour":
                    raw = bytearray(self._raw(old))
                    for offset in range(0, len(raw) - 11, 4):
                        file_id, pid = struct.unpack_from("<iq", raw, offset)
                        if file_id == 0 and pid in mapping:
                            raw[offset:offset + 12] = _pointer(mapping[pid])
                    if old == source["display"]:
                        name, end = _string(raw, FIELDS_OFFSET)
                        if name != template:
                            raise ValueError("Template button does not match its perk")
                        raw = raw[:FIELDS_OFFSET] + _encode_string(perk) + raw[end:]
                    clone.set_raw_data(bytes(raw))
                    written[new] = bytes(raw)
                    continue
                data = self._translate(self._typetree(old), mapping)
                if old == source["mount"]:
                    data["m_Father"]["m_PathID"] = group["transform"]
                    data["m_LocalPosition"]["x"] = x - group["x"]
                    data["m_LocalPosition"]["y"] = y - group["y"]
                if original.type.name == "GameObject":
                    if data["m_Name"] == template:
                        data["m_Name"] = perk
                    elif old == mount_object:
                        data["m_Name"] = f"Mount_{perk}"
                written[new] = self._save_typetree(new, data)
            # Parent the new mount under the chosen branch group.
            parent_data = self._typetree(group["transform"])
            parent_data["m_Children"].append({"m_FileID": 0, "m_PathID": mapping[source["mount"]]})
            written[group["transform"]] = self._save_typetree(group["transform"], parent_data)
            # Add a panel entry, copied from the template's entry with its header cleared.
            new_display = mapping[source["display"]]
            panel = self.objects[group["quadrant"]]
            raw = self._raw(group["quadrant"])
            _, entries = parse_quadrant(raw)
            template_quadrant = self._raw(tree["groups"][source["group"]]["quadrant"])
            _, template_entries = parse_quadrant(template_quadrant)
            start, end, _ = next(e for e in template_entries if e[2] == source["display"])
            entry = template_quadrant[start:end]
            offset = 0
            for _ in range(2):
                _, offset = _string(entry, offset)
            _, header_end = _string(entry, offset)
            entry = entry[:offset] + _encode_string("") + entry[header_end:]
            entry = entry.replace(_pointer(source["display"]), _pointer(new_display), 1)
            title, offset = _string(raw, FIELDS_OFFSET)
            insert = next((e[1] for e in entries if e[2] == source["display"]), len(raw))
            raw = (raw[:offset] + struct.pack("<I", len(entries) + 1) + raw[offset + 4:insert]
                   + entry + raw[insert:])
            if parse_quadrant(raw)[1][-1][1] != len(raw):
                raise ValueError("Branch panel update failed verification")
            panel.set_raw_data(raw)
            written[group["quadrant"]] = raw
            # Register the button with the tree.
            tree_obj = self.objects[tree["tree"]]
            raw = self._raw(tree["tree"])
            displays, end = parse_tree(raw)
            raw = (raw[:FIELDS_OFFSET] + struct.pack("<I", len(displays) + 1) + raw[FIELDS_OFFSET + 4:end]
                   + _pointer(new_display) + raw[end:])
            tree_obj.set_raw_data(raw)
            written[tree["tree"]] = raw
            tree["nodes"].append({"perk": perk, "group": group_name, "display": new_display,
                                  "mount": mapping[source["mount"]], "x": x, "y": y})
        return written

    def save(self, written):
        result = self.scene.save()
        reopened = next(iter(UnityPy.load(result).files.values()))
        if set(reopened.objects) != set(self.objects):
            raise ValueError("Scene object table failed verification")
        for pid, data in written.items():
            if reopened.objects[pid].get_raw_data() != data:
                raise ValueError(f"Scene object {pid} failed round-trip verification")
        return result


def add_manifest_paths(manifest, assets):
    """Make sure every data_assets asset is listed in manifest.dat.

    assets is a list of (bundle container path, asset name). The game resolves
    assets by path through manifest.dat, building the path from the asset ID, so
    a path missing from the manifest fails with "no asset path info found". New
    paths reuse the manifest's spelling of the same folder and the asset name's
    case. Returns (manifest bytes with unrelated bytes preserved, added paths).
    """
    import json

    document = json.loads(manifest)
    row = next((r for r in document["bundleInfos"] if r["name"] == "data_assets"), None)
    if row is None:
        raise ValueError("manifest.dat has no data_assets entry")
    existing = {p.casefold() for r in document["bundleInfos"] for p in r["assets"]}
    folders = {}
    for path in row["assets"]:
        folders.setdefault(path.rsplit("/", 1)[0].casefold(), path)
    result = manifest
    added = []
    for container, name in assets:
        if container.casefold() in existing:
            continue
        folder, filename = container.rsplit("/", 1)
        if filename.casefold() != f"{name}.asset".casefold():
            continue  # not addressed by asset name
        neighbour = folders.get(folder.casefold())
        if neighbour is None:
            raise ValueError(f"manifest.dat has no folder matching {container}")
        proper = f'{neighbour.rsplit("/", 1)[0]}/{name}.asset'
        needle = json.dumps(neighbour).encode()
        if result.count(needle) != 1:
            raise ValueError(f"Could not place {proper} in manifest.dat")
        result = result.replace(needle, needle + b"," + json.dumps(proper).encode(), 1)
        row["assets"].insert(row["assets"].index(neighbour) + 1, proper)
        existing.add(proper.casefold())
        added.append(proper)
    if json.loads(result) != document:
        raise ValueError("manifest.dat update failed verification")
    return result, added
