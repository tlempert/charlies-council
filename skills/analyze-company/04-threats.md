# Step 3.5 — Moat Threat Search

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} threats started`

Execute three layers of threat queries to surface non-obvious risks the experts would otherwise miss.

**3.5a — Static template queries (LLM-adapted):**

For each moat type (up to 3), generate ONE search query per threat dimension (Regulatory, Adjacent Invasion, Tech Shift) using the templates below as starting points. ADAPT each template to be specific and web-searchable for the company's industry and geography. If a template is nonsensical for this industry, REPLACE it with a relevant query in the same threat dimension.

| Moat Type | Regulatory | Adjacent Invasion | Tech Shift |
|-----------|-----------|-------------------|------------|
| info_asymmetry | "{product} mandatory data sharing open access regulation {country}" | "{company} customers building own {product} data capability in-house" | "AI aggregation scraping bypass {industry} portal direct access" |
| network_effects | "{industry} interoperability forced access mandate regulation {country}" | "{product} supplier going direct-to-consumer bypassing {company}" | "AI agent direct matching removing need for {industry} marketplace" |
| pricing_power | "{company} excessive pricing fee cap price control regulation investigation" | "{industry} free or subsidized alternative undercutting {company}" | "low-cost alternative commoditizing {product} margin compression" |
| switching_costs | "{product} data portability right to transfer regulation {country}" | "major platform bundling {product} capability reducing need for {company}" | "AI agent automating {product} workflow replacing specialized tool" |
| regulatory_capture | "{company} {designation} reform deregulation removing protected status" | "government or state-backed alternative replacing {company} {designation} role" | "technology making {designation} regulatory function obsolete" |
| scale_economies | "{company} {industry} antitrust size cap forced divestiture" | "aggregation platform enabling small {industry} competitors to match {company} scale" | "AI automation reducing minimum efficient scale in {industry}" |
| consumer_brand | "{company} {product} marketing restriction health labeling regulation {country}" | "creator economy DTC micro-brand displacing {company} market share" | "{company} brand reputation crisis generational relevance shift" |
| platform_ecosystem | "{company} forced open access sideloading app store regulation" | "{product} open-source fork or developer defection to competing platform" | "cloud streaming {product} eliminating need for {company} dedicated platform" |
| data_flywheel | "{company} data collection privacy consent regulation {country}" | "synthetic data replacing {company} proprietary training data advantage" | "open-source model commoditizing {company} AI capability" |
| resource_ownership | "{industry} nationalization windfall tax royalty increase {country}" | "recycling circular economy reducing demand for {product}" | "synthetic lab-grown alternative replacing {product} material" |
| contract_concession | "{company} license concession contract non-renewal government review" | "new entrant awarded competing concession in {industry} {country}" | "technology bypass making {industry} concession role unnecessary" |
| ip_patents | "{company} key patent expiry generic alternative competition timeline" | "compulsory licensing {product} government override {country}" | "open-source alternative eliminating need for {company} license" |

**Supplementary templates** — also generate if applicable to this company:
- switching_costs: `"{product} right to repair independent service legislation {country}"`
- pricing_power (if government is a major customer): `"{company} government procurement excess pricing sole source reform"`
- pricing_power: `"{company} customer churn rate after price increase historical trend"` and `"{company} customer response to price increase competitor switching"` (skip for luxury/Veblen goods where higher prices increase demand — e.g., Hermès, Ferrari, LVMH)
- scale_economies: `"{company} largest customer building in-house {product} capability vertical integration"`
- consumer_brand: `"{company} {product} safety recall contamination crisis brand trust"`
- network_effects or platform_ecosystem: `"{company} {customer_type} unit economics cost revenue ROI using platform"` (where {customer_type} is the paying/supply side of the marketplace — e.g., "estate agent", "driver", "merchant", "host". For two-sided marketplaces, query the supply side that generates revenue for the platform)

**3.5b — Cross-cutting queries (always run, mechanically filled):**

Fill in the company's variables and run all 7:

1. `"government state-owned public alternative to {industry} {country}"`
2. `"{product} ban phase-out restriction health safety environmental regulation {country}"`
3. `"{company} export control sanctions tariff trade restriction"`
4. `"{company} {industry} antitrust forced divestiture breakup"`
5. `"{product} regulatory reclassification status change enforcement {country}"`
6. `"{company} {industry} tariff trade war subsidy dispute bilateral retaliation"`
7. `"{product} {industry} environmental compliance cost mandate ESG regulation {country}"`

**3.5c — Dynamic queries (5, LLM-generated):**

Generate 5 ADDITIONAL search queries specific to this company that the templates and cross-cutting queries above WOULD NOT produce. Think about:
- How is this exact industry regulated in OTHER countries? What precedents exist abroad?
- What happened to analogous companies in adjacent markets?
- What lawsuits, legislative proposals, or regulatory consultations target THIS company right now?
- What customer consolidation, demographic shrinkage, or labor regulation affects THIS specific market?
- What latent liabilities (environmental, legal, reputational) could surface?

Rules: each query must name the specific company/industry/country. Do NOT repeat what static or cross-cutting already cover.

**3.5d — Execute all queries via Python (write to file, NOT stdout):**

```bash
./venv/bin/python3 -c "
from modules.config import tavily
queries = [
    # paste all ~21-24 queries here as strings
]
with open('/tmp/silicon_council/{TICKER}/raw_moat_threats.txt', 'w') as f:
    for q in queries:
        try:
            response = tavily.search(query=q, search_depth='basic', max_results=2)
            for r in response.get('results', []):
                f.write(f'THREAT: {r[\"title\"]}\nCONTENT: {r[\"content\"][:500]}\n\n')
        except Exception as e:
            f.write(f'Search failed for {q}: {e}\n')
" && wc -c /tmp/silicon_council/{TICKER}/raw_moat_threats.txt
```

Only the byte count returns to your context. Do NOT `cat` this file. Then triage it exactly as in Step 2.2:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/jev_snippets.py {TICKER} "{COMPANY NAME}" /tmp/silicon_council/{TICKER}/raw_moat_threats.txt
```

On `jev: CACHED`, the drops and pairing are in `raw_moat_threats.jev.md`; read its `## Dropped` section.

**3.5e — Condense the threat dump into a register (Codex):**

Mechanical, high-volume, zero judgment — offload it:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the raw moat-threat search results below into a structured threat register for an investment analyst.

Rules:
- One entry per distinct threat. Merge duplicates that appear across queries.
- For each entry give: THREAT (one line) / EVIDENCE (facts, numbers, dates, verbatim) / SOURCE (article title) / STATUS (enacted, proposed, speculative, or rumoured).
- Preserve every number and date exactly. Never infer, round, or extrapolate.
- Do NOT rank threats by severity and do NOT assess the moat. You are registering, not judging.
- Drop entries with no identifiable source. Target 600-1000 words."; echo; cat $D/raw_moat_threats.kept.txt 2>/dev/null || cat $D/raw_moat_threats.txt; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/threat_register.md >$D/threat_register.log 2>&1; wc -c $D/threat_register.md
```

**Fallback:** if `$CX` is missing or `threat_register.md` is empty (check the byte count, not the exit code), use `raw_moat_threats.txt` in place of the register below and tell the user the Codex leg was skipped.

**3.5f — Append the register to the refined dossier:**

Substitute the actual moat types, then append without routing the text through your context:

```bash
D=/tmp/silicon_council/{TICKER}; { echo; echo "--- MOAT THREAT SEARCH ---"; echo "MOAT TYPES: [type1], [type2], [type3]"; echo; cat $D/threat_register.md; } >> $D/refined_dossier.md && wc -c $D/refined_dossier.md
```

This ensures all 12 experts see the moat-threat data when they read the dossier.

**3.5g — Neutrality reader on the appended dossier (Jev):** Then ask a reader that did not write it. Jev reads every section and paragraph and answers two questions the writer cannot answer about its own text: does the wording argue beyond its sourced facts, and does the paragraph tell the reader what to conclude. Warning sections (data integrity, data quality, pipeline defects, what is unresolved) are skipped by title — a warning is not a steer.

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/jev_neutrality.py /tmp/silicon_council/{TICKER}/refined_dossier.md
```

On `jev: CACHED`, read the last line of `jev_neutrality.md` — it is the same NEUTRAL/STEERING verdict.

Strip or rewrite each section and paragraph it lists, then re-run. Proceed when it prints `NEUTRAL`, or when every remaining item is one you can justify in a sentence (a threat entry that quotes a vendor's own words, say — then strip the adjectives and keep the facts). On KNSL it put two threat-register entries at the top of the list (0.84 and 0.80): both were a vendor's own marketing copy — "flexible, scalable, highly configurable" — that had reached twelve experts as evidence. `jev: SKIPPED` means no second reader this run; say so and rely on the self-check above.

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/council_manifest.py evidence {TICKER} && ./venv/bin/python3 scripts/evidence_ledger.py build /tmp/silicon_council/{TICKER}
```

The hash is the evidence pack every expert and the synthesist read; `evidence_ledger.json` is the list of facts the synthesis must use or set aside. `jev: SKIPPED` → no ledger this run; say so.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} threats done`
