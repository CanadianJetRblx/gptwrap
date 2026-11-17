import random

from dataset_v2 import build, verify as V

DUMP = {"Classes": [
    {"Name": "Instance", "Superclass": "<<<ROOT>>>", "Tags": [], "Members": [
        {"MemberType": "Function", "Name": "Destroy", "Tags": []},
        {"MemberType": "Property", "Name": "Name", "Tags": []}]},
    {"Name": "Players", "Superclass": "Instance", "Tags": ["Service"], "Members": []},
    {"Name": "ServerStorage", "Superclass": "Instance", "Tags": ["Service"], "Members": []},
    {"Name": "Part", "Superclass": "Instance", "Tags": [], "Members": [
        {"MemberType": "Function", "Name": "PivotTo", "Tags": []}]},
    {"Name": "BodyVelocity", "Superclass": "Instance", "Tags": ["Deprecated"], "Members": []},
    {"Name": "Folder", "Superclass": "Instance", "Tags": [], "Members": []},
    {"Name": "Frame", "Superclass": "Instance", "Tags": ["NotCreatable"], "Members": []},
]}
API = ApiIndex = V.ApiIndex.from_dump(DUMP)

GOOD = """--!strict
-- Keeps a per-player inventory and syncs it to the client.
-- Handles join and leave events, validates the saved data, and
-- exposes a small API used by the shop module.
local Players = game:GetService("Players")
local inventory = {}
local function onAdded(player: Player)
    inventory[player.UserId] = {}
    task.wait(1)
end
local function onRemoving(player: Player)
    inventory[player.UserId] = nil
end
Players.PlayerAdded:Connect(onAdded)
Players.PlayerRemoving:Connect(onRemoving)
return {}
"""


def test_good_file_passes_all_checks():
    v = V.verify("inv.server.luau", GOOD, API)
    assert v.ok and v.errors == [] and "structure" in v.checks


def test_bad_service_and_instance_are_caught():
    assert not V.verify("a.luau", 'local x = game:GetService("Playerz")', API).ok
    assert not V.verify("a.luau", 'local x = Instance.new("Frame")\nlocal y = Instance.new("Nope")', API).ok


def test_unknown_method_is_a_soft_warning_and_file_defined_method_is_clean():
    v = V.verify("a.luau", "local p = workspace:GetChlidren()", API)
    assert v.ok and any("unknown member" in w for w in v.warnings)     # may be defined in another module
    v2 = V.verify("a.luau", "local o = {}\nfunction o:Sum() return 1 end\nlocal z = o:Sum()", API)
    assert v2.ok and not v2.warnings


def test_structure_errors():
    assert not V.verify("a.luau", "local function f()\n  if x then\n    print(1)\nend\n", API).ok
    assert V.verify("a.luau", "local v = if x then 1 else 2\nprint(v)", API).ok   # if-expression has no end
    assert not V.verify("a.luau", 'print("unterminated)', API).ok


def test_client_cannot_touch_server_services():
    assert not V.verify("hud.client.luau", 'local s = game:GetService("ServerStorage")', API).ok
    assert V.verify("hud.server.luau", 'local s = game:GetService("ServerStorage")', API).ok


def test_licence_is_recorded_not_filtered():
    rec = {"id": "x", "text": GOOD, "kind": "code",
           "meta": {"repo": "acme/inv", "path": "a.luau", "license": "GPL-3.0", "roblox_repo": True}}
    cpt, sft, hold, man = build.build([rec], API)
    assert cpt and cpt[0]["licence"] == "GPL-3.0"
    assert build.repo_bucket("someone/project") in ("train", "holdout")
    assert build.repo_bucket("x/y") == build.repo_bucket("X/Y")          # case-insensitive, stable


def test_debug_task_only_when_fault_is_detected_and_fix_passes():
    rng = random.Random(3)
    t = build.build_debug_task(GOOD, "inv.server.luau", API, rng)
    assert t is not None
    assert t["messages"][1]["content"].count("```") == 2
    assert V.verify("inv.server.luau", GOOD, API).ok
    assert t["fault_detected_by"] and t["verifier_output"]


def test_header_comment_extraction_skips_licence_text():
    assert build.comment_header(GOOD).startswith("Keeps a per-player inventory")
    lic = "-- MIT License\n-- Copyright (c) 2020\n-- Permission is hereby granted\nlocal x = 1"
    assert build.comment_header(lic) is None


def test_end_to_end_small_build_has_provenance():
    rec = {"id": "r1", "text": GOOD, "kind": "code",
           "meta": {"repo": "acme/inv", "path": "inv.server.luau", "license": "MIT", "roblox_repo": True, "stars": 3}}
    cpt, sft, hold, man = build.build([rec] * 3, API, debug_share=1.0)
    assert man["seen"] == 3 and man.get("drop:exact_duplicate") == 2
    assert cpt[0]["licence"] == "MIT" and cpt[0]["repo"] == "acme/inv" and cpt[0]["checks"]
