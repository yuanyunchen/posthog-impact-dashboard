
## Independent audit notes (read before ranking; they override wording in the reports)
An independent audit re-checked the inputs against raw data. Apply these corrections:
1. Ratios: Gilbert09's 130 major episodes are 3.5× the next candidate (37), not 6.5×. After removing ~864 templated add-source/table PRs he still has ~119 major episodes.
2. `trust_rank` is approval-network centrality: high values mean receiving approvals from central reviewers. It does not show who is "the most trusted approver".
3. `downstream_authors` counts later authors of the same files, a proxy for touching shared code. It is not proof that others built on or adopted his work.
4. Quality rates were recomputed with a consistent numerator and denominator (the matrix is already updated). Several reports quote old values, so use the matrix. pauldambra is not the lowest-quality candidate.
5. Self-repair (an author fixing or reverting his own PRs) was invisible to the follow-up-fix metric. Treat self-repair chains in reports as a quality caveat, not as a clean record. Work merged after 2026-10-20 has no observable quality signal yet.
6. Approval type: 36% of all merged PRs (40% of human-authored) were approved only by an AI bot. Review-based quality signals are not comparable across people with very different AI-only shares.
7. Describe what merged and its rollout scope. "Completed everywhere" needs deployment or adoption evidence, which the data does not contain.
8. Two candidates (eli-r-ph, MattBro) were added after the audit found the earlier shortlist missed them. Judge them on the same standard; their lower PR volume is not a reason to rank them lower.
