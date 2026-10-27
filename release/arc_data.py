"""Loader for the ARC dataset v1.0. Standard library only; pandas is used when you ask for it.

    import arc_data as arc
    eps = arc.load_episodes()                        # list of dicts
    df  = arc.load_service_labels(pandas=True)       # DataFrame
    ids = arc.episode_ids(protocol="unseen_system", role="train")

    # raw files of one episode, after extracting its part's archive into ./raw_data
    ep = arc.load_episode("ep_held_arc_b001_1", root="raw_data")     # {"services": [...], "edges": [...], ...}

Tables are looked up next to this file, or in the folder given by `root` / the environment variable ARC_DATA_DIR.
"""
import csv, gzip, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
PROTOCOLS = ("in_system", "unseen_system", "unseen_fault", "held_out_faults", "higher_load", "noise_ceiling")
_NUMERIC_HINT = ("n_", "p_", "y_", "bad_", "delay", "load_rate", "block", "position", "is_", "usable", "saturated", "stalled",
                 "t_recover", "recovered", "user_damage", "collateral", "action_on", "healthy")


def _dir(root):
    return os.path.expanduser(root or os.environ.get("ARC_DATA_DIR") or HERE)


def _num(v):
    if v in ("", None):
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v and "e" not in v.lower() else f
    except ValueError:
        return v


def _read(name, root=None, pandas=False):
    path = os.path.join(_dir(root), name + ".csv.gz")
    if pandas:
        import pandas as pd
        return pd.read_csv(path)
    with gzip.open(path, "rt", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in r.items():
            if k.startswith(_NUMERIC_HINT):
                r[k] = _num(v)
    return rows


def load_episodes(root=None, pandas=False):
    """One row per episode (campaign, calibration and the one unusable episode); see the `kind` and `usable` columns."""
    return _read("episodes", root, pandas)


def load_service_labels(root=None, pandas=False):
    """One row per (episode, service): counts, bad-request shares, y_mean / y_peak at three bars, verdict, recovery."""
    return _read("service_labels", root, pandas)


def load_client_flows(root=None, pandas=False):
    return _read("client_flows", root, pandas)


def load_splits(root=None, pandas=False):
    """Columns: episode_id, part, then one column per protocol holding 'train', 'test', 'repeat' or ''."""
    return _read("splits", root, pandas)


def episode_ids(protocol, role, root=None):
    """Episode ids that have the given role ('train' or 'test') in the protocol, e.g. ('unseen_system', 'test')."""
    if protocol not in PROTOCOLS:
        raise ValueError(f"protocol must be one of {PROTOCOLS}")
    return [r["episode_id"] for r in load_splits(root) if r.get(protocol) == role]


def scored(rows, min_requests=30):
    """Service rows with at least `min_requests` requests before and after the action (the rows that are scored)."""
    return [r for r in rows if (r["n_before"] or 0) >= min_requests and (r["n_after"] or 0) >= min_requests]


def load_episode(episode_id, root):
    """Raw files of one episode from an extracted archive: <root>/<part>/raw/<episode_id>/ (any part)."""
    root = os.path.expanduser(root)
    for part in sorted(os.listdir(root)):
        d = os.path.join(root, part, "raw", episode_id)
        if os.path.isdir(d):
            break
    else:
        raise FileNotFoundError(episode_id)
    out = {"path": d, "meta": json.load(open(os.path.join(d, "meta.json"))),
           "labels": json.load(open(os.path.join(d, "labels_v2.json")))}
    for name in ("services", "edges", "counters", "op_counters", "client"):
        p = os.path.join(d, name + ".csv.gz")
        if os.path.exists(p):
            with gzip.open(p, "rt", newline="") as f:
                out[name] = list(csv.DictReader(f))
    return out
