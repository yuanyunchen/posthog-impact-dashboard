使用 skill：ponytail、workspace-management

**进度**

- Completed read-only checks using `python3 -I`. No files modified.
- All **109 distinct PR references in the five reports’ core-contribution sections** exist, fall within the window, and match the named engineer through `credited_to`.

**问题**

The main weaknesses are candidate selection, an actual quality-rate calculation bug, and claims that give activity proxies more meaning than the data supports.

1. **Blocker — the shortlist does not establish an organization-wide Top 5.**

   Across **all authors present in triage**, 15 of the top 30 by major PR count are absent from the 20 analyst reports:

   | Excluded engineer | Major PRs | Excluded engineer | Major PRs |
   |---|---:|---|---:|
   | eli-r-ph | 51 | MattBro | 26 |
   | meikelmosby | 26 | mariusandra | 25 |
   | jzhu13 | 24 | z0br0wn | 22 |
   | jose-sequeira | 22 | yasen-posthog | 21 |
   | andehen | 18 | a-lider | 18 |
   | orian | 18 | robbie-c | 18 |
   | nickbest-ph | 18 | benjackwhite | 17 |
   | jurajmajerik | 16 | | |

   This is not just a volume objection. eli-r-ph has **32 major episodes**, versus webjunkie’s 31, haacked’s 28 and pauldambra’s 20. His evidence includes capture rate limiting, person deduplication and database failover fixes: #78014, #81532, #82047, #86792. MattBro has **21 major episodes**, including OAuth token binding and revocation work.

   MattBro, nickbest-ph and benjackwhite are absent from recall itself despite having triage records. Consequently, downstream agreement cannot validate their exclusion. Also, triage covers **15,473 of 16,318 human-attributed window PRs**, so this comparison still cannot identify every omitted contender.

   **Fix:** analyze the strongest omitted engineers and compare them directly against ranks 3–6 before claiming a repository-wide Top 5.

2. **Major — quality rates use mismatched numerator and denominator.**

   [The calculation](../impact/coarse/run.py#L18) divides **all affected mature PRs** by only mature PRs triaged substantive or higher. Routine, trivial and mechanical failures therefore lower a rate whose denominator excludes those PRs.

   Recomputing affected PRs within the eligible population gives:

   | Engineer | Published quality rate | Consistent calculation |
   |---|---:|---:|
   | Gilbert09 | 0.981 | **0.986 — 22/1,628 affected** |
   | webjunkie | 0.975 | **0.983 — 6/359** |
   | pauldambra | 0.934 | **0.952 — 11/228** |
   | Piccirello | 0.954 | **0.966 — 3/87** |
   | haacked | 0.966 | **0.980 — 3/149** |

   pauldambra is **no longer the pool’s lowest-quality candidate**; frankh and rafaeelaudibert are below him under this corrected definition. That directly invalidates part of his final explanation and several comparisons.

   **Fix:** intersect affected PRs with eligible PRs, then regenerate quality percentiles, reference scores and comparison inputs.

3. **Major — Gilbert09’s decisive comparison exaggerates the gap, and “discounted volume” is not fully enforced.**

   His **130 major episodes are verified**. “6.5 times the next candidate’s” is wrong: Piccirello has **37**, making the ratio **3.51×**. The 6.5× comparison selects pauldambra’s 20 because he is second on a *different* metric.

   The claim that episodes prevent PR splitting from raising scores is also false mathematically: `max + 0.25 × rest` awards **8 points for one major PR, 10 for two**, even inside one episode. Separate files or weeks can fragment a single program further.

   A deliberately broad title filter found **864 add-source/table PRs**, including **40 major PRs**. Removing that identified set leaves Gilbert09 with **119 major episodes** and tier-based episode mass **4,219**, versus pauldambra’s **1,398**. His lead survives this particular stress test, but “130 after templated PRs are set aside” is not the computation actually reported.

   **Fix:** correct the ratio; publish the exact catalogue exclusion and its counterfactual score; assess coherent programs and outcomes alongside episode counts.

4. **Major — the quality evidence systematically misses self-repair and recent failures.**

   [Follow-up detection](../impact/recall/features.py#L76) deliberately excludes fixes by the original author. Thus haacked’s four corrective PRs after #124397 do not reduce his follow-up-fix metric. The same blind spot affects CSP and credentials-service repair chains.

   Quality rates also exclude PRs merged after **October 20**, while headline evidence includes October 29–November 2 changes. The report acknowledges several repairs, but the quantitative “clean record” does not evaluate much of the flagship late work.

   **Fix:** report self-repair separately, group repairs with the originating program, and show mature versus not-yet-observable quality. Do not treat zero recorded failures as demonstrated reliability.

5. **Major — “trust,” “building on his work” and review adoption are overstated.**

   The numbers largely reproduce, but their interpretation does not:

   - **Trust rank:** approval edges run **reviewer → author**. High PageRank measures receiving approvals from central people; it does not establish who is the “most trusted approver.”
   - **Downstream authors:** 106/106/100 reproduce for Gilbert09/webjunkie/pauldambra. These count later edits to files previously touched, with hub exclusions. They do not establish dependency on, adoption of, or benefit from that engineer’s contribution.
   - **Adoption:** webjunkie gave **24 change-request review events on 22 PRs**. The reported **0.955 is 21/22 PRs**, using subsequent approval plus multiple commits as a proxy. It does not prove that 95% of 24 requested changes were implemented.

   **Fix:** retain the counts with literal labels—approval-network centrality, subsequent same-file authors, and change-request resolution proxy—and use review content or actual adoption evidence for stronger claims.

6. **Major — AI-only approval is widespread, but “no recorded review” misdescribes it.**

   Recomputed approval sets show **6,782/18,715 PRs (36.2%)** approved only by `stamphog`. Among human-attributed PRs, it is **6,600/16,318 (40.4%)**.

   | Finalist | Stamphog-only approvals | Share of own PRs |
   |---|---:|---:|
   | Gilbert09 | 1,572/2,939 | 53.5% |
   | webjunkie | 213/559 | 38.1% |
   | pauldambra | 365/652 | 56.0% |
   | Piccirello | 38/144 | 26.4% |
   | haacked | 117/246 | 47.6% |

   Gilbert09 has human approvals on **1,363 PRs**. Most of the remainder have recorded AI approval, so “about 1,200 with no recorded review” is both numerically loose and semantically misleading.

   This does not prove low impact. It does weaken comparisons based on approval rates and apparent lack of review friction.

   **Fix:** distinguish human-approved, AI-only-approved and no-approval PRs, including a breakdown for major work.

7. **Major — several explanations turn scoped changes into completed universal outcomes.**

   - **Webhook transport:** #101508 explicitly repairs silent-loss behavior introduced during migration to the shared transport. Credit should include that history. Those two cited PRs alone do not demonstrate the claimed outcome across eight providers.
   - **Storage migration:** #124397 restricts query rewriting and explicitly describes unsupported query shapes and an **89-day** read limit. #126076 removes a rollout flag; it does not prove unrestricted historical compatibility or universal production cutover.
   - **CA remediation:** #121580 contains rollout exceptions; it also caused an MCP crash loop and was rolled back by **adboio in #121721**, before Piccirello’s #122294 repair. “Removed from every runtime within three days” needs build/deployment evidence and shared incident credit.
   - **Credentials:** #125029 verifies migration of SDK call sites in 21 products. It does not by itself establish completed remote credentials-service adoption by all 21.

   **Fix:** describe what merged, state the rollout scope and limitations, and reserve “completed everywhere” for observed deployment/adoption evidence.

8. **Minor — ranking arithmetic is consistent; its published procedural description is not.**

   Verified:

   - Both decisions rank the first four identically.
   - haacked is **5th/6th**; rafaeelaudibert **6th/5th**.
   - They tie at **11 Borda points**; reference score initially places rafaeelaudibert fifth.
   - haacked wins their direct comparison in **both presentation orders**.
   - All **five pairwise matchups** have consistent winners across orders.
   - Borda totals, boundary resolution, **Kendall τ = 0.853**, final gates and sensitivity frequencies reproduce.

   However, `consensus_voters` claims **three voters including R**, while the code uses **two**, with R only breaking ties. The displayed gate says **2/3 of rankers**, while execution requires **both deciders’ top seven**. The displayed quality gate omits the additional **8% absolute follow-up threshold**; all candidates’ observed rates are below it, so that part of the gate rejects nobody.

   Piccirello’s **0% reference-weight top-five frequency** and haacked’s **59.8%** are accurate, but measure reference-score weight sensitivity, not uncertainty in the entire selection process.

   **Fix:** align the method description with execution and scope the robustness claim explicitly.

9. **Minor — the report’s “almost entirely hand-written” claim is unsupported.**

   haacked’s report infers this from six AI co-author trailers. Yet **40/246 PR descriptions explicitly mention Claude, Codex, robots or agent assistance**, including flagship work. Missing co-author trailers cannot establish manual authorship.

   **Fix:** describe trailer prevalence as an incomplete disclosure signal and remove the hand-written inference.

The following claim checks provide a compact evidence ledger. “Verified” means supported by the local records, not independently observed in production. Every PR below passed existence, window and attribution checks.

| Specific claim | Status | Evidence |
|---|---|---|
| Gilbert09 merged 2,939 PRs | **Verified** | Direct count of in-window `credited_to` records |
| Gilbert09 has 130 major episodes | **Verified** | Recomputed using episode grouping and triage |
| His major count is 6.5× the next candidate | **Wrong** | Next-highest is 37; ratio 3.51× |
| #110610 addresses fleet-wide loader stalls | **Verified** | Title/body describe all V3 loader pods stalled |
| #113196 addresses duplicate append rows | **Verified** | Title/body describe rollback of unfinished runs |
| #114623 prevents billing of late-created jobs | **Verified** | Failed rows are not billed; older rows explicitly excluded |
| #125029 migrates call sites in 21 products | **Verified** | PR body explicitly identifies 21 products |
| Gilbert09 has 106 downstream authors | **Verified as proxy** | Rebuilt lineage events reproduce 106 |
| webjunkie’s granian pin addresses dashboard latency | **Verified** | #104208 documents ~6s → 15–20s regression and cause |
| #103852 consolidates ownership reading | **Verified** | Shared reader replaces fragmented product readers |
| webjunkie approves 48 authors across 21 teams | **Verified** | Rebuilt human approval events and team map |
| His 24 change requests were 95% adopted | **Wrong as stated** | 24 events; proxy is 21 of 22 PRs |
| He is the most trusted approver | **Unverifiable** | PageRank direction measures approval recipients |
| webjunkie has 0 reverts, 9 fixes over 516 mature PRs | **Verified** | Mature-window explicit-reference detector reproduces counts |
| pauldambra merged 652 PRs | **Verified** | Direct in-window attribution count |
| Boot document shrank from 544 KB to 10 KB | **Verified, reported build result** | #94059 states built-template sizes |
| Lazy relation batching covers 275 team-scoped models | **Verified, scope** | #126463 describes the default and iterator exception |
| #126768 adds a CI regression guard | **Verified** | New upward imports fail the frontend layer check |
| #83929 addresses a production OAuth incident | **Verified** | Body reports incident traces and excessive token queries |
| #108163 prevents managed integration/token state loss | **Verified** | Body identifies overwritten conversation settings |
| pauldambra is lowest on quality at 0.934 | **Wrong** | Consistent calculation is 0.952; third-lowest |
| None of his 20 major PRs was reverted/peer-fixed | **Verified within detector** | No major IDs intersect detected affected PRs |
| Piccirello has 37 major episodes, second of 20 | **Verified** | Recomputed 42 major PRs → 37 episodes |
| #114423 unifies permission precedence | **Verified** | Central resolver; partner provisioning retains an exception |
| #116719 enforces CSP on shared/embedded pages | **Verified, scoped** | Self-hosted and bare exporter exceptions remain |
| CA remediation reached every shipped runtime in three days | **Unverifiable** | Merge records show repairs; production deployment coverage absent |
| haacked’s #110254 introduces events-write cutover | **Verified, conditional** | Applies to `FLAG_EVALUATIONS_ONLY` organizations |
| #126076 removes the HogQL rollout flag | **Verified** | Organization mode becomes the controlling condition |
| #117395 closes a filtered-deletion gap | **Verified, scoped** | Handles flag rows without events copies; some predicates refused |
| haacked has 12 distinct review requesters | **Verified** | Rebuilt request events reproduce 12 |

**Overall verdict — five lines**

The five are plausible high-impact engineers, but this analysis does not yet establish the organization’s strongest five.  
Gilbert09’s lead survives the catalogue-removal stress test, although the stated 6.5× advantage is false.  
webjunkie and pauldambra have substantial shared-platform evidence; trust and quality claims need correction.  
Piccirello and haacked are defensible judgment calls, with rollout caveats and meaningful boundary uncertainty.  
Reopen omitted contenders and repair the quality calculation before presenting the ranking as settled; production outcomes remain unverified.

Codex session ID: 01a1a3e2-9960-7771-a964-5ae201f3c61c
Resume in Codex: codex resume 01a1a3e2-9960-7771-a964-5ae201f3c61c
