"""Team collaboration network for the dashboard (spec docs/superpowers/specs/2026-11-03-dashboard-content.md §F).

Nodes are people (coarse 20 + bridges + community review hubs + importance-flow top, ≤ NODE_CAP); edges are relations
aggregated by kind (review / continue / fix) with their underlying PRs. Layout is precomputed here so the page opens
stable. CLI: python -m impact.site_network <prs_path> <out_dir> <site_dir> → <site_dir>/network_data.json + .js"""
import json
import math
import random
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx

from impact import config as C
from impact.episodes import group_episodes
from impact.fine import team_graph as TG

NODE_CAP, FLOW_TOP, NEIGHBOR_CAP, EDGE_PRS = 60, 40, 30, 10
OVERVIEW_PER_KIND = 25          # default per-kind top-N in the overview (≤ 150 allowed by §F; 25 keeps it airy)
CORE_EDGES_PER_KIND = 80        # core–core edges shipped per kind = slider max (overview pool, titled PR lists)
# shortcut: 800KB budget (page loads lazily). Focus-only edges list their top EGO_EDGE_PRS PRs; review relations
# also link to the full GitHub search.
EGO_EDGE_PRS = 5
MAX_BYTES = 800_000
TITLE_MAX = 72
KIND = {"approve": "review", "changes_requested": "review", "comment": "review",
        "continue": "continue", "revert": "fix", "followup_fix": "fix"}
EV_CODE = {"approve": "A", "changes_requested": "R", "comment": "C", "continue": "D", "revert": "V", "followup_fix": "F"}
MAJOR_UP = {"major", "landmark"}
W, H = 1100, 700                # layout canvas (cytoscape model units ≈ px at the overview zoom)
LAYOUT_K, LAYOUT_ITER, SQUASH_AT, NODE_GAP = 4.5, 600, 1.8, 12
HUB, HUB_TIE, COMM_TIE = "\0centre", .2, .15


def load_points(triage: list[dict]) -> tuple[dict[int, int], dict[int, str]]:
    """Triage tier points per PR; llm_error rows count as untriaged."""
    tier = {t["number"]: t["tier"] for t in triage if not t.get("llm_error") and t.get("tier") in C.TIER_POINTS}
    return {n: C.TIER_POINTS[t] for n, t in tier.items()}, tier


def aggregate(events: list[dict], points: dict[int, int]) -> dict[tuple, dict]:
    """(src, dst, kind) → {w, n, prs}. Weight = sum of distinct PR points (review, continue) or distinct PR count (fix).
    prs: ≤ EDGE_PRS of [number, event codes, date], points desc then date desc."""
    acc = defaultdict(dict)
    for e in events:
        k = KIND.get(e["type"])
        if not k:
            continue  # review_request: not drawn (§F table), data covers ~30 PRs
        rec = acc[e["src"], e["dst"], k].setdefault(e["pr"], [set(), e["at"] or ""])
        rec[0].add(EV_CODE[e["type"]])
        if e["at"] and e["at"] < rec[1]:
            rec[1] = e["at"]  # earliest event of this pair on the PR
    out = {}
    for key, by_pr in acc.items():
        w = len(by_pr) if key[2] == "fix" else sum(points.get(n, 0) for n in by_pr)
        ranked = sorted(sorted(by_pr.items(), key=lambda kv: (kv[1][1], kv[0]), reverse=True),
                        key=lambda kv: -points.get(kv[0], -1))  # points desc, then newest first (stable sort)
        ev = Counter(c for codes, _ in by_pr.values() for c in codes)  # distinct PRs per event type, e.g. A = approved
        out[key] = {"w": w, "n": len(by_pr), "ev": dict(sorted(ev.items())),
                    "prs": [[n, "".join(sorted(ev)), at[:10]] for n, (ev, at) in ranked[:EDGE_PRS]]}
    return out


def clip(text: str | None, n: int) -> str | None:
    """First sentence, cut at a word boundary to ≤ n chars (hover cards stay one or two lines)."""
    if not text:
        return None
    t = text.strip().split(". ")[0].rstrip(".")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def profiles(cands: list[str], site_data: dict | None, reports: dict[str, dict]) -> dict[str, dict]:
    """Shortlisted people as the dashboard shows them: trait tags and the 3 raw facts (site_data facts[]), rank and
    stability (top5/next5), positioning and network summary; report.json role is the fallback when site_data lacks them."""
    sd = site_data or {}
    ranked = {r["login"]: r for r in (sd.get("top5") or []) + (sd.get("next5") or [])}
    out = {}
    for login in cands:
        c, r, rep = (sd.get("candidates") or {}).get(login) or {}, ranked.get(login) or {}, reports.get(login) or {}
        facts = c.get("facts") or r.get("facts") or []
        role = c.get("role") or rep.get("role") or {}
        traits = list(dict.fromkeys(f["trait"] for f in facts if f.get("trait")))[:3] or \
            [t for t in [role.get("primary_role")] if t]
        out[login] = {"traits": traits, "facts": [[f.get("value_text") or str(f.get("value")), f.get("label")] for f in facts[:3]],
                      "pos": clip(c.get("positioning") or rep.get("positioning"), 130),
                      "net": clip(role.get("network_summary"), 170), "stab": r.get("stability"),
                      "flags": len(c.get("red_flags") or rep.get("red_flags") or [])}
    return out


def insights(tg: dict, cands: list[str], top5: list[str]) -> list[dict]:
    """3–4 network facts for the clickable strip; nodes = people the chip highlights."""
    bridges = [b["login"] for b in tg.get("bridges") or []]
    comms = [c for c in tg.get("communities") or [] if c["size"] >= 10 and c["purity"] is not None]  # tiny ones are trivially pure
    sp = tg.get("single_points") or []
    out = [{"text": f"{sum(b in cands for b in bridges)} of the top {len(bridges)} bridges are shortlisted",
            "note": "Bridges = highest betweenness on the review graph: people whose reviews connect otherwise separate groups.",
            "nodes": bridges}]
    if comms:
        lo, hi = min(c["purity"] for c in comms), max(c["purity"] for c in comms)
        out.append({"text": f"Review communities ≠ org teams ({lo:.0%}–{hi:.0%} on the main team)",
                    "note": f"In the {len(comms)} review communities of 10+ people, the most common org team is only "
                            f"{lo:.0%}–{hi:.0%} of members. Highlighted: each one's main reviewer.",
                    "nodes": [c["hub"] for c in comms]})
    out.append({"text": f"{len(sp)} single point{'s' if len(sp) != 1 else ''} of approval" if sp else
                "No area hangs on one approver",
                "note": f"An area counts when one person gives ≥{C.SINGLE_POINT_SHARE:.0%} of ≥{C.SINGLE_POINT_MIN} approvals." +
                ("" if sp else " None found in this window."), "nodes": sorted({x["approver"] for x in sp})})
    if top5:
        nb = sum(t in bridges for t in top5)
        out.append({"text": f"Where the Top 5 sit ({nb} are bridges)", "note": "The five highest-ranked engineers.", "nodes": top5})
    return out


def pick_nodes(coarse: list[str], flow: list[str], bridges: list[str], hubs: list[str], cap: int = NODE_CAP) -> tuple[list, list]:
    """Priority order: coarse 20, bridges, community hubs, importance-flow top FLOW_TOP; deduped, cut at cap.
    Returns (picked, cut) so the cut is reported, never silent."""
    order = list(dict.fromkeys(coarse + bridges + hubs + flow[:FLOW_TOP]))
    return order[:cap], order[cap:]


def neighbors(login: str, edges: dict[tuple, dict], cap: int = NEIGHBOR_CAP) -> list[str]:
    """One-hop neighbours ranked by total review+continue points, then PR count; fix-only ties last."""
    score = defaultdict(lambda: [0, 0])
    for (s, t, k), e in edges.items():
        if login in (s, t):
            o = t if s == login else s
            score[o][0] += e["w"] if k != "fix" else 0
            score[o][1] += e["n"]
    return [o for o, _ in sorted(score.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:cap]]


def diameter(flow: float, top: float, shortlisted: bool) -> float:
    """Node diameter in layout units; the page draws exactly this. Non-shortlisted people are drawn at 80% so the
    shortlisted 20 stand out (size still ranks importance flow within each group)."""
    return round((9 + 37 * math.sqrt(max(flow, 0) / (top or 1))) * (1 if shortlisted else .8), 1)


def _squash(pos: dict, nodes: list) -> None:
    """Pull weakly tied outliers in: radius beyond SQUASH_AT × median keeps only 20% of its excess (direction kept)."""
    cx, cy = sum(pos[p][0] for p in nodes) / len(nodes), sum(pos[p][1] for p in nodes) / len(nodes)
    med = sorted(math.dist(pos[p], (cx, cy)) for p in nodes)[len(nodes) // 2] or 1
    for p in nodes:
        r = math.dist(pos[p], (cx, cy))
        if r > SQUASH_AT * med:
            f = (SQUASH_AT * med + .2 * (r - SQUASH_AT * med)) / r
            pos[p] = (cx + (pos[p][0] - cx) * f, cy + (pos[p][1] - cy) * f)


def _separate(pos: dict, box: dict, movable: list, gap: float = NODE_GAP, rounds: int = 80) -> None:
    """Collision pass on each person's box (disc plus, for named people, the label under it): push overlapping
    boxes apart along the axis of least overlap, deterministic order; nodes not in movable stay put."""
    mv = set(movable)
    nodes = sorted(pos)
    for _ in range(rounds):
        moved = False
        for a, b in combinations(nodes, 2):
            if a not in mv and b not in mv:
                continue
            (ax, ay), (bx, by) = pos[a], pos[b]
            (ahw, aup, adn), (bhw, bup, bdn) = box.get(a, (6, 6, 6)), box.get(b, (6, 6, 6))
            ox = min(ax + ahw, bx + bhw) - max(ax - ahw, bx - bhw) + gap
            oy = min(ay + adn, by + bdn) - max(ay - aup, by - bup) + gap
            if ox <= 0 or oy <= 0:
                continue
            if ox < oy:
                dx, dy = (ox if bx >= ax else -ox), 0.0
            else:
                dx, dy = 0.0, (oy if by >= ay else -oy)
            sa = .5 if a in mv and b in mv else 1.0 if a in mv else 0.0
            pos[a], pos[b] = (ax - dx * sa, ay - dy * sa), (bx + dx * (1 - sa), by + dy * (1 - sa))
            moved = True
        if not moved:
            break


def boxes(size: dict, named: set) -> dict:
    """(half width, extent above, extent below) per person; named people reserve their label (mono 11px ≈ 6.6px/char)."""
    out = {}
    for p, d in size.items():
        r = d / 2
        out[p] = (max(r, (6.6 * len(p) + 8) / 2), r, r + 17) if p in named else (r, r, r)
    return out


def layout(core: list[str], extra: list[str], edges: dict[tuple, dict], comm: dict[str, int | None],
           box: dict[str, tuple] | None = None, seed: int = C.SEED) -> dict[str, tuple[float, float]]:
    """spring_layout on the core, initialised by community (community centres on a circle); outliers squashed in,
    scaled into W×H, overlaps removed. Extra (focus-only) nodes are then placed with the core fixed, so the overview
    never moves."""
    box = box or {}
    rng = random.Random(seed)
    cids = sorted({comm.get(p) for p in core}, key=lambda c: (c is None, c if c is not None else 0))
    centre = {c: (math.cos(2 * math.pi * i / len(cids)), math.sin(2 * math.pi * i / len(cids))) for i, c in enumerate(cids)}

    def graph(nodes):
        g = nx.Graph()
        g.add_nodes_from(nodes)
        ns = set(nodes)
        for (s, t, k), e in edges.items():
            if s in ns and t in ns:
                w = math.log1p(e["w"] if k != "fix" else 4 * e["w"])
                g.add_edge(s, t, weight=g.get_edge_data(s, t, {"weight": 0})["weight"] + w)
        top = max((d["weight"] for *_, d in g.edges(data=True)), default=1)
        for *_, d in g.edges(data=True):
            d["weight"] = math.sqrt(d["weight"] / top)  # in [0, 1]: comparable with the ties below
        for a, b in combinations(nodes, 2):  # same review community pull together, so its region is readable
            if comm.get(a) is not None and comm.get(a) == comm.get(b):
                g.add_edge(a, b, weight=g.get_edge_data(a, b, {"weight": 0})["weight"] + COMM_TIE)
        for p in nodes:  # weak tie to a virtual centre so disconnected people are not flung off the canvas
            g.add_edge(HUB, p, weight=HUB_TIE)
        return g

    init = {p: (centre[comm.get(p)][0] + rng.uniform(-.25, .25), centre[comm.get(p)][1] + rng.uniform(-.25, .25)) for p in core}
    init[HUB] = (0.0, 0.0)
    pos = nx.spring_layout(graph(core), pos=init, weight="weight", k=LAYOUT_K / math.sqrt(len(core)), iterations=LAYOUT_ITER, seed=seed)
    pos = {p: tuple(v) for p, v in pos.items()}
    _squash(pos, core)
    xs, ys = [pos[p][0] for p in core], [pos[p][1] for p in core]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    fit = lambda x, y: ((x - x0) / ((x1 - x0) or 1) * W, (y - y0) / ((y1 - y0) or 1) * H)
    out = {p: fit(*pos[p]) for p in core}
    _separate(out, box, core)
    if extra:
        g = graph(core + extra)
        init2 = {p: tuple(pos[p]) for p in core + [HUB]}
        for p in extra:  # start next to the strongest core neighbour
            nb = max((q for q in g[p] if q in out and q != HUB), key=lambda q: g[p][q]["weight"], default=None)
            bx, by = pos[nb] if nb else (rng.uniform(x0, x1), rng.uniform(y0, y1))
            init2[p] = (bx + rng.uniform(-.08, .08), by + rng.uniform(-.08, .08))
        pos2 = nx.spring_layout(g, pos=init2, fixed=core + [HUB], weight="weight", k=LAYOUT_K / math.sqrt(len(core)), iterations=120, seed=seed)
        mx, my = (x1 - x0) * .08, (y1 - y0) * .08
        for p in extra:
            x = min(max(pos2[p][0], x0 - mx), x1 + mx)
            y = min(max(pos2[p][1], y0 - my), y1 + my)
            out[p] = fit(x, y)
        _separate(out, box, extra)
    return {p: (round(x, 1), round(y, 1)) for p, (x, y) in sorted(out.items())}


def person(login: str, own: list[dict], tier: dict[int, str], tg_people: dict, team_map: dict, flow: dict) -> dict:
    """Hover facts: team, main area, PR count, major+ episodes, first-pass rate, importance flow."""
    m = tg_people.get(login) or {}
    tri = [p for p in own if p["number"] in tier and C.TIER_POINTS[tier[p["number"]]] > 0]
    majors = None
    if any(p["number"] in tier for p in own):
        majors = sum(any(tier[n] in MAJOR_UP for n in ep) for ep in group_episodes(tri))
    areas = Counter()
    for p in own:  # main area, weighted by PR points so substantial work outweighs config churn
        if a := TG.pr_area(p):
            areas[a] += C.TIER_POINTS.get(tier.get(p["number"]), 1) or .1
    fpr = (m.get("first_pass_rate") or {}).get("value")
    return {"team": team_map.get(login) or m.get("team") or [], "comm": m.get("community"),
            "area": areas.most_common(1)[0][0] if areas else None, "prs": len(own), "majors": majors,
            "fpr": fpr, "fpr_n": (m.get("first_pass_rate") or {}).get("n"),
            "flow": round((flow.get(login) or {}).get("total", 0.0), 1)}


def assemble(prs: list[dict], events: list[dict], triage: list[dict], tg: dict, coarse: list[dict],
             final: dict | None, team_map: dict | None, site_data: dict | None = None,
             reports: dict[str, dict] | None = None) -> dict:
    points, tier = load_points(triage)
    win = [p for p in prs if p["in_window"]]
    flow, flow_src = tg.get("importance_flow") or {}, "team_graph.json"
    if not (tg.get("summary") or {}).get("points_seeded_prs"):  # team_graph built before triage existed
        flow, flow_src = TG.importance_flow(win, points, events), "recomputed from triage.jsonl (team_graph.json had no points)"
    edges = aggregate(events, points)

    comm_list = tg.get("communities") or []
    comm = {m: c["id"] for c in comm_list for m in c["members"]}
    cands = [c["login"] for c in coarse if c.get("selected_by", True)]
    core, cut = pick_nodes(cands, list(flow), [b["login"] for b in tg.get("bridges") or []], [c["hub"] for c in comm_list])

    ego = {p: neighbors(p, edges) for p in core}
    extra = sorted({q for ns in ego.values() for q in ns} - set(core))
    flow_of = lambda p: (flow.get(p) or {}).get("total", 0.0)
    top_flow = max(flow_of(p) for p in core + extra)
    size = {p: diameter(flow_of(p), top_flow, p in cands) for p in core + extra}
    pos = layout(core, extra, edges, comm, boxes(size, set(cands)))

    # edges shipped: per kind the top CORE_EDGES_PER_KIND among core nodes (overview pool, full PR lists),
    # plus every edge between a core person and his ≤ NEIGHBOR_CAP neighbours (focus view, EGO_EDGE_PRS listed)
    coreset = set(core)
    by_kind = defaultdict(list)
    for key in edges:
        if key[0] in coreset and key[1] in coreset:
            by_kind[key[2]].append(key)
    pool = set()
    for keys in by_kind.values():
        keys.sort(key=lambda x: (-edges[x]["w"], -edges[x]["n"], x))
        pool |= set(keys[:CORE_EDGES_PER_KIND])
    allow = {key: EDGE_PRS for key in pool}  # PRs listed per shipped edge
    for p, ns in ego.items():
        r = set(ns)
        for key in edges:
            q = key[1] if key[0] == p else key[0] if key[1] == p else None
            if q in r:
                allow[key] = max(allow.get(key, 0), EDGE_PRS if key[2] == "fix" else EGO_EDGE_PRS)
    kept = sorted(allow, key=lambda x: (x[2], -edges[x]["w"], -edges[x]["n"], x))
    plist = lambda key: edges[key]["prs"][:allow[key]]

    own = defaultdict(list)
    for p in win:
        if (o := TG._owner(p)):
            own[o].append(p)
    rank = {r["login"]: r["rank"] for r in (final or {}).get("top5") or []}
    order = core + extra
    pid = {p: i for i, p in enumerate(order)}
    tgp = tg.get("people") or {}
    prof = profiles(cands, site_data, reports or {})
    bridge = {b["login"]: (i + 1, b["communities_reached"]) for i, b in enumerate(tg.get("bridges") or [])}
    single = defaultdict(list)
    for x in tg.get("single_points") or []:
        single[x["approver"]].append(x["area"])
    people = [{"id": p, **person(p, own[p], tier, tgp, team_map or {}, flow),
               "x": pos[p][0], "y": pos[p][1], "d": size[p], "core": p in coreset, "cand": p in cands, "rank": rank.get(p),
               # human-reviewed PRs: denominator for "x approved N of his PRs (S%)"
               "rev_n": ((tgp.get(p) or {}).get("changes_requested_rate") or {}).get("n"),
               "bridge": {"rank": bridge[p][0], "reach": bridge[p][1]} if p in bridge else None,
               "single": single.get(p) or None, **({"prof": prof[p]} if p in prof else {})}
              for p in order]

    by_num = {p["number"]: p for p in prs}
    tiers = list(C.TIER_POINTS)
    used = sorted({n for key in kept for n, _, _ in plist(key)})
    pr_tab = {str(n): [by_num[n]["title"][:TITLE_MAX], tiers.index(tier[n]) if n in tier else None,
                       by_num[n]["merged_at"][5:10]] for n in used}

    bx = boxes(size, set(cands))
    taken = [(pos[p][0] - bx[p][0], pos[p][1] - bx[p][1], pos[p][0] + bx[p][0], pos[p][1] + bx[p][2]) for p in core]

    def blob(c):
        ms = [people[pid[m]] for m in core if comm.get(m) == c["id"]]
        if len(ms) < 2:
            return None
        cx, cy = sum(m["x"] for m in ms) / len(ms), sum(m["y"] for m in ms) / len(ms)
        sx = math.sqrt(sum((m["x"] - cx) ** 2 for m in ms) / len(ms))
        sy = math.sqrt(sum((m["y"] - cy) ** 2 for m in ms) / len(ms))
        rx, ry = sx + 36, sy + 36
        hw = (5.6 * len(c["main_team"] or "mixed") + 6) / 2  # 9px mono uppercase label
        for lx, ly in ((cx, cy - ry - 7), (cx, cy + ry + 7), (cx - rx * .6, cy - ry * .8 - 7), (cx + rx * .6, cy - ry * .8 - 7)):
            r = (lx - hw, ly - 7, lx + hw, ly + 7)
            if not any(r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3] for t in taken):
                taken.append(r)
                break
        else:
            lx = ly = None  # no free spot outside the hull: no label on the canvas, the legend still names it
        rd = lambda v: None if v is None else round(v)
        return [round(cx), round(cy), round(rx), round(ry), len(ms), rd(lx), rd(ly)]

    communities = [{"id": c["id"], "team": c["main_team"], "purity": c["purity"], "size": c["size"],
                    "top_teams": c["top_teams"], "hub": c["hub"], "blob": blob(c)}
                   for c in comm_list if any(comm.get(m) == c["id"] for m in order)]
    return {
        "meta": {"window": [C.WINDOW_START[:10], C.WINDOW_END[:10]], "repo": C.REPO,
                 "placeholder": not rank, "rank_source": "final.json" if rank else None,
                 "flow_source": flow_src, "seed": C.SEED, "tiers": tiers, "tier_points": list(C.TIER_POINTS.values()),
                 "counts": {"core": len(core), "focus_only": len(extra), "edges": len(kept), "prs": len(pr_tab),
                            "events": dict(Counter(e["type"] for e in events)),
                            "triaged_prs": len(points), "window_prs": len(win)},
                 "caps": {"nodes": NODE_CAP, "flow_top": FLOW_TOP, "neighbors": NEIGHBOR_CAP, "edge_prs": EDGE_PRS,
                          "ego_edge_prs": EGO_EDGE_PRS, "overview_per_kind": OVERVIEW_PER_KIND,
                          "core_edges_per_kind": CORE_EDGES_PER_KIND, "title_chars": TITLE_MAX},
                 "cut_nodes": cut, "insights": insights(tg, cands, [r["login"] for r in (final or {}).get("top5") or []])},
        "communities": communities,
        "people": people,
        # [src, dst, kind r|c|f, weight, distinct PRs, overview-pool flag, ["<pr><event codes>", …], {code: PRs}]
        "edges": [[pid[s], pid[t], k[0], edges[(s, t, k)]["w"], edges[(s, t, k)]["n"], int((s, t, k) in pool),
                   [f"{n}{ev}" for n, ev, _ in plist((s, t, k))], edges[(s, t, k)]["ev"]] for s, t, k in kept],
        "ego": {str(pid[p]): [pid[q] for q in ego[p]] for p in core},  # neighbours, strongest first
        "prs": pr_tab,
    }


def build(prs_path: Path, out_dir: Path, site_dir: Path) -> dict:
    from impact.normalize import load
    out_dir, site_dir = Path(out_dir), Path(site_dir)
    need = [out_dir / f for f in ("team_graph.json", "coarse.json", "triage.jsonl")]
    if missing := [str(p) for p in need if not p.exists()]:
        raise FileNotFoundError(f"site_network needs {missing}")
    opt = lambda p: json.loads(p.read_text()) if p.exists() else None
    prs = load(Path(prs_path))
    rd = {r["number"]: r for r in map(json.loads, open(C.REVIEW_DETAIL))} if C.REVIEW_DETAIL.exists() else None
    events = TG.build_events(prs, rd, opt(C.LINEAGE))
    coarse = opt(out_dir / "coarse.json")
    reports = {c["login"]: r for c in coarse if (r := opt(out_dir / "candidates" / c["login"] / "report.json"))}
    data = assemble(prs, events, [json.loads(l) for l in open(out_dir / "triage.jsonl")], opt(out_dir / "team_graph.json"),
                    coarse, opt(out_dir / "final.json"), opt(C.TEAM_MAP), opt(site_dir / "site_data.json"), reports)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode()) >= MAX_BYTES:
        raise ValueError(f"network_data.json would be {len(text.encode())} bytes ≥ {MAX_BYTES}")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "network_data.json").write_text(text)
    (site_dir / "network_data.js").write_text(f"window.NETWORK_DATA = {text};\n")  # loads from file:// too (no fetch)
    print(json.dumps({"bytes": len(text.encode()), **{k: v for k, v in data["meta"]["counts"].items() if k != "events"},
                      "placeholder": data["meta"]["placeholder"], "flow_source": data["meta"]["flow_source"],
                      "cut_nodes": len(data["meta"]["cut_nodes"])}))
    return data


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: python -m impact.site_network <prs_path> <out_dir> <site_dir>")
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
