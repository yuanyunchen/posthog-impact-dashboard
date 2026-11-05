from impact.fine.context import MAX_BYTES, build


def pr(n, author, product, credited=True):
    return {"number": n, "title": f"feat({product}): x", "author": author, "credited_to": author if credited else None,
            "in_window": True, "merged_at": f"2026-09-{1 + n % 28:02d}T00:00:00Z", "additions": 40, "deletions": 0,
            "files": [{"path": f"products/{product}/backend/f{n}.py", "additions": 40, "deletions": 0}], "reviews": []}


def world(n_people=200, n_areas=120, n_teams=60):
    people = [f"dev{i}" for i in range(n_people)]
    prs = [pr(i, people[i % n_people], f"prod{i % n_areas}") for i in range(6000)]
    prs += [pr(9000, "renovate", "prod1"), pr(9001, "posthog", "prod2", credited=False)]
    triage = [{"number": p["number"], "tier": ["major", "substantive", "routine", "mechanical"][p["number"] % 4]} for p in prs]
    changelog = {str(i): [{"title": f"Entry {i % 300}", "date": "2026-09-10"}] for i in range(0, 6000, 7)}
    team_map = {p: [f"team{i % n_teams}"] for i, p in enumerate(people)} | {"renovate": ["bots"]}
    graph = {"summary": {"people": n_people, "events": {"approve": 100}},
             "communities": [{"id": c, "members": people[c::20] + ["github-actions"], "main_team": f"team{c}", "purity": 0.5,
                              "hub": people[c], "hub_reviews_inside": 10} for c in range(20)],
             "bridges": [{"login": "stamphog", "betweenness": 0.9, "community": 0, "communities_reached": 9}]
                        + [{"login": people[i], "betweenness": 0.1, "community": 0, "communities_reached": 3} for i in [150, *range(11)]],
             "single_points": [], "trust_rank": {p: i / n_people for i, p in enumerate(people)}}
    cands = people[:20]
    roles = {c: {"top_area": "Product: prod0", "top_area_share": 0.5, "top_area_is_top": True} for c in cands}
    return build(prs, triage, changelog, team_map, graph, cands, roles)


def test_size_bound_no_bots_and_candidates_marked():
    md = world()
    assert len(md.encode()) <= MAX_BYTES
    for bot in ("renovate", "stamphog", "github-actions", "posthog"):
        assert bot not in md
    assert "`company.human_prs`=6000" in md  # bot-authored and uncredited AI PRs excluded
    assert "★dev0" in md and "| dev150 |" in md and "★dev150" not in md  # only the 20 candidates carry the mark
    assert "other (105 areas)" in md  # tail beyond the top 15 summed, not dropped
    assert md.count("| dev") >= 20  # one candidate row each in section 5


def test_missing_graph_is_unknown():
    md = build([pr(1, "a", "x")], [], None, None, None, ["a"])
    assert "collaboration structure unknown" in md and "| a | unknown |" in md


def test_inferred_team_is_labelled_not_official():
    md = build([pr(1, "a", "feature_flags")], [], None, {}, None, ["a"],
               {"a": {"top_area": "Product: Feature flags", "top_area_share": 1.0, "team_inferred": "feature-flags"}})
    assert "| a | feature-flags (inferred from area) |" in md
