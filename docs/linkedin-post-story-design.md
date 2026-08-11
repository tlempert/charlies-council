# LinkedIn Post — Story Design: Charlie's Council

Story: **"Munger's latticework of mental models — compiled to software, and made dynamic."**

High-level story design for a LinkedIn post about the Charlie's Council / Silicon Council
project, plus craft guidance for building the post itself.

---

## 1. Positioning — what this post is actually about

Not "I built an AI stock picker" — that framing attracts skeptics and tip-seekers and
buries what's original here.

The wedge — the founding insight of the project — is **Charlie Munger's multi-disciplinary
mental models**. Munger's claim: you cannot evaluate a business with finance knowledge
alone; you need a *latticework* of models from psychology, biology, history, mathematics —
"to the man with only a hammer, every problem looks like a nail." Everyone quotes this.
Almost nobody practices it, because the bottleneck was always one lifetime, one head.

The post's claim: **AI removes that bottleneck.** Charlie's Council is the latticework
made executable — each discipline is an agent, they all study the same evidence in
parallel, and a synthesized Munger resolves their disagreements. And unlike Munger's
latticework, this one is **dynamic**: it adapts its lenses to each specific company and
grows by adding a file.

Target audience, in order: engineers/PMs building with LLMs → AI-curious professionals →
thoughtful investors. The spectacle (a Biologist analyzing a stock) is the hook; the
big idea (mental models are now runnable, adaptive software) is the payload.

**Naming:** use **Charlie's Council** in the post (repo name), not "Silicon Council"
(README name). The story is Munger's; the name should be too.

---

## 2. The one idea (recommended angle)

> **"Munger said great investing takes mental models from a dozen disciplines. Nobody can
> master a dozen disciplines. So I hired all of them — as AI agents. And where Munger's
> latticework was fixed in his head, mine adapts to every company it studies."**

Why this angle wins:

- **It's the actual origin story.** The council roster proves it's not a gimmick: a
  Biologist, a Historian, an Anthropologist, and a Psychologist sit alongside Buffett and
  Burry. Those four ARE the latticework — evolutionary ecology, pattern-matching across
  disruptions, cultural durability, behavioral analysis. The project is a thesis about
  *how thinking works*, wearing an investing costume.
- **It rides a famous idea and extends it.** "Latticework of mental models" has enormous
  name recognition (Poor Charlie's Almanack, Farnam Street). The post doesn't have to
  explain the concept — it gets to complete it: *the latticework was always
  bandwidth-limited; LLMs make it executable and adaptive.* Familiar setup, novel payoff.
- **"Dynamic" is the differentiator.** Munger's models were static — a fixed toolkit
  applied from memory. The system tailors its interrogation per company (see §3). That's
  the part no one has heard before, and it's honest engineering, not hype.
- **It scales beyond investing.** The closing lesson — "you can now run worldly wisdom
  the way you run code, and extend it like code" — applies to any domain. That's what
  makes it shareable outside finance.

One post = one idea. The "teaching it to say 'too hard'" angle (previous draft) becomes a
supporting beat here and its own follow-up post later.

---

## 3. What "dynamic" means concretely (ground the claim in the repo)

The post must cash the word "dynamic" with specifics, or it reads as filler. The system
is dynamic in four real ways:

1. **The interrogation adapts per company.** The forensic step generates
   company-specific red-flag queries (this CEO, this lawsuit, this named disruptor —
   "CoStar for Rightmove, OpenAI for a SaaS company"), not a fixed checklist.
   (`skills/analyze-company.md`, Step 2)
2. **The threat search adapts per moat.** The system first detects WHICH moat types the
   company has (network effects, switching costs, brand, data flywheel…), then generates
   threat queries specific to that moat across three dimensions — regulatory, adjacent
   invasion, tech shift — plus 5 novel queries the templates would never produce.
   (Step 3.5: ~21–24 tailored queries per company)
3. **The framework shifts with the problem type.** Every analysis first classifies what
   *kind* of problem the stock is — clean analytical / regime-political / cyclical /
   binary event / narrative-momentum — and the analytical framework changes accordingly.
   A regime-risk case is not analyzed like a DCF case. (Business Explainer taxonomy)
4. **The latticework itself is extensible.** Each discipline is a markdown file. The
   council grew from 8 experts to 12 (Lynch, Biologist, Historian, Anthropologist added
   later) without touching orchestration. Adding a Game Theorist tomorrow = writing one
   file.

(Bonus, if space allows: the synthesis is dynamic too — Moat Tribunal votes mechanically
raise or lower the valuation floor/ceiling per company.)

Pick 2–3 of these for the post; all four is too many. Recommended: #2 (moat-adaptive
threat search — most vivid), #3 (problem-type classification — most intellectual), #4
(extensible roster — most practical for builders).

---

## 4. Narrative arc — beat by beat

Arc: hook → the famous idea → the bottleneck → the build → the twist (dynamic) → the
discipline → universal lesson → invitation.

**Beat 1 — Hook (first ~200 chars, before the "…see more" fold).**
The surprise roster, or the hammer. Example shape: *"My stock-analysis AI includes a
Biologist, a Historian, and an Anthropologist. That's not a gimmick. It's Charlie
Munger's oldest idea — finally executable."*

**Beat 2 — The famous idea (2–3 lines).**
Munger's latticework: you can't judge a business with finance alone — you need mental
models from psychology, biology, history. "To the man with only a hammer, every problem
looks like a nail." Most analysis — human and AI — is one hammer.

**Beat 3 — The bottleneck (1–2 lines).**
Everyone quotes the latticework. Almost nobody practices it — because practicing it
required being Charlie Munger: one head, sixty years, a dozen disciplines.

**Beat 4 — The build (3–5 lines).**
So I hired the disciplines as AI agents. The Biologist asks: keystone species or parasite
about to lose its host? The Historian studies what killed every company that looked like
this one (the Yellow Pages test). The Anthropologist asks whether the product is a
ritual, a utility, or a status symbol — and whether the next generation will care. The
Psychologist reads the CEO's earnings-call answers for fluff. Alongside them: Buffett on
moats, Burry on forensic accounting, Lynch as the designated bull. Twelve lenses, one
evidence-tagged dossier, all in parallel — then a synthesized Munger resolves their
fights.

**Beat 5 — The twist: dynamic (2–4 lines).**
Munger's latticework was static — fixed models, applied from memory. Mine adapts: it
detects which moats the company actually has and generates ~20 bespoke threat searches
for exactly those moats; it classifies what *kind* of problem the stock is (clean DCF
case? regime risk? binary event?) and shifts framework; and the lattice grows by adding a
markdown file — the council went from 8 minds to 12 without touching the engine.

**Beat 6 — The discipline (2–3 lines).**
The deepest Munger feature survived translation: the system is allowed to say TOO
UNCERTAIN — the "Too Hard" pile. Tribunal votes cap valuations, the bull case must be
answered, a red-team Ghost of Munger audits every verdict. Its most valuable outputs are
the ones where it refuses to conclude.

**Beat 7 — The universal lesson (1–2 lines, the shareable bit).**
Mental models were always the right idea, bottlenecked by human bandwidth. LLMs remove
the bottleneck: worldly wisdom is now something you can run per decision, adapt per case,
and extend like code — in any domain, not just stocks.

**Beat 8 — Invitation (1–2 lines + housekeeping).**
Comment-bait that actually works: *"Which discipline would you add to the council?"*
(People love casting this — expect Game Theorist, Supply-Chain Engineer, Regulator,
Short Seller…) Repo/architecture in first comment. Disclaimer: personal project, not
investment advice.

---

## 5. Story assets mined from the repo (use these, they're gold)

**The latticework made literal (the four discipline experts):**
- Biologist: "Is this a keystone species or a parasite about to lose its host?" —
  keystone / symbiont / parasite classification (`skills/experts/biologist.md`)
- Historian: "Your job is to study what happened to companies that looked exactly like
  this one" — dead analogues: Yellow Pages, Blockbuster, BlackBerry, Kodak
  (`skills/experts/historian.md`)
- Anthropologist: "Is it a ritual, a utility, or a status symbol? … 'Google it' is a
  cultural verb. 'Use Bing' — nobody says this." (`skills/experts/anthropologist.md`)
- Psychologist: "Did management answer questions directly or use fluff?"
  (`skills/experts/psychologist.md`)

**Munger canon to invoke (public domain of ideas, high recognition):**
- "Latticework of mental models" / elementary worldly wisdom
- "To the man with only a hammer, every problem looks like a nail."
- The "Too Hard" pile as the biggest source of his edge

**Quotable lines already written into the system:**
- "If every analysis keeps returning BUY/WAIT/HOLD, you are not performing Munger's
  discipline — you are performing AI confidence bias." (`skills/munger-synthesis.md`)
- "You are the GHOST OF CHARLIE MUNGER… call EBITDA 'bullshit earnings.'"
  (`skills/reality-check.md`)
- Lynch: "You are the COUNTER-WEIGHT to the bears… find what the pessimists are missing."

**Concrete numbers (specificity = credibility):**
- 12 expert agents in parallel (~5 min wall clock vs ~35 sequential) + Munger synthesis
  + red team + a Feynman-style teacher
- ~21–24 moat-threat queries generated per company, tailored to detected moat types
- 5 problem types; 6-word verdict vocabulary: BUY / WAIT / HOLD / PASS / SELL /
  TOO UNCERTAIN
- 5-expert Moat Tribunal; 3+ SEVERE flags mechanically drop valuation to the Graham floor
- Every number source-tagged: [SEC] / [CALC] / [SEARCH] / [MEDIA]
- Council grew 8 → 12 experts by adding markdown files

---

## 6. Craft guidelines — how to build the post best

**Format mechanics:**
- Length: ~1,200–1,700 characters for this arc (hard cap 3,000). Every beat above is 1–5
  short lines.
- LinkedIn renders no markdown. Short paragraphs (1–2 lines), generous white space,
  one-line list items only, at most 1–2 emojis if any.
- The first ~200 characters appear before the fold — the hook must live entirely there
  and end on an open loop.
- No external links in the body (reach penalty). Repo/dashboard link in the first
  comment, posted immediately.
- 3–5 niche hashtags max (#BuildingWithAI #MentalModels #AIAgents #Investing), no soup.

**Visual (strongly recommended):**
- Best fit for THIS angle: a latticework diagram — 12 named lenses (with one-line
  obsessions: "keystone or parasite?", "the Yellow Pages test", "ritual or status
  symbol?") converging into the Munger synthesis, with the red team looping back. The
  lattice IS the thesis; make the picture BE the lattice.
- Alternative: dashboard hero-card screenshot of a real verdict (a WAIT or TOO UNCERTAIN
  is itself proof of discipline).
- Ambitious: 7–8 slide carousel, one beat per slide — highest-dwell format on LinkedIn.

**Voice rules:**
- First person, past tense, builder's humility. "I noticed," "I rewrote," "it still gets
  X wrong."
- Concrete beats clever: real expert names, real query counts, real verdicts.
- One idea. Anything serving the other angles gets cut and banked for the series.
- Include exactly one flaw or open problem — perfection reads as fiction and kills
  comments.

**Distribution:**
- Post Tue–Thu morning in your audience's timezone.
- Reply to every comment in the first hour; answer the first technical question with a
  mini-thread (it becomes the bridge to Post 2).
- Disclaimer line at the end: "Personal project for my own decisions — nothing here is
  investment advice."

---

## 7. Hook options (A/B pick)

1. **The roster surprise (recommended):** "My stock-analysis AI includes a Biologist, a
   Historian, and an Anthropologist. Not a gimmick — it's Charlie Munger's oldest idea,
   finally executable."
2. **The hammer:** "'To the man with only a hammer, every problem looks like a nail.'
   Most stock analysis — human and AI — is one hammer. I built a toolbox that argues."
3. **The impossible prerequisite:** "Munger said great investing takes mental models from
   a dozen disciplines. Nobody can master a dozen disciplines. So I hired all of them —
   as AI agents."
4. **The upgrade claim:** "Charlie Munger spent 60 years wiring a latticework of mental
   models into one head. I compiled mine into software — and made it adapt to every
   company it studies."

Recommendation: #1 or #3. #1 opens on concrete surprise (best scroll-stopper); #3 states
the thesis fastest. #2 is the best *second line* regardless of which hook wins.

---

## 8. Series roadmap (after the main post lands)

1. **This post** — The dynamic latticework: Munger's mental models as adaptive software
2. **"Teaching my AI to say 'too hard'"** — confidence bias, TOO UNCERTAIN verdict,
   tripwires, the red team (judgment/AI-engineering crowd; previous draft's angle)
3. **"My codebase is mostly markdown now"** — the Gemini-pipeline → Claude-skills pivot;
   experts as .md files; Python demoted to data plumbing (engineering crowd)
4. **"Engineered disagreement"** — designated bull, Moat Tribunal voting, red-team audit;
   ensembles need structure, not just multiple opinions (agent-architecture crowd)
5. **"20 reports, 20 frameworks"** — the teacher layer and problem-type taxonomy; what
   the human learns (investing/learning crowd)

Each follow-up reuses the same arc: hook → flaw → build → payoff → lesson → question.
