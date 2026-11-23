"""Game modules. Each returns a report.GameReport."""
from .arknights import Arknights
from .bluearchive import BlueArchive
from .endfield import Endfield
from .genshin import Genshin
from .wuthering import WutheringWaves
from .zzz import ZenlessZoneZero

# The default order. Blue Archive, ZZZ and Genshin go last: they may wait for their server's
# daily reset. Genshin is the slowest and least predictable, so a timeout there can't hold up
# the rest. The player can change the order on Home; ordered() applies it.
GAMES = [Endfield, Arknights, WutheringWaves, BlueArchive, ZenlessZoneZero, Genshin]
GAMES_BY_ID = {g.id: g for g in GAMES}


def ordered(cfg):
    """The games in the player's order (config "order"). Unknown ids are ignored, and games
    the saved order doesn't mention yet (added in a newer version) follow in default order."""
    chosen = [gid for gid in dict.fromkeys(cfg.get("order") or []) if gid in GAMES_BY_ID]
    return [GAMES_BY_ID[gid] for gid in chosen] + [g for g in GAMES if g.id not in chosen]


def move(cfg, gid, step):
    """Move a game up (step -1) or down (+1) in the player's order."""
    ids = [g.id for g in ordered(cfg)]
    i = ids.index(gid)
    j = max(0, min(len(ids) - 1, i + step))
    ids.insert(j, ids.pop(i))
    cfg["order"] = ids
