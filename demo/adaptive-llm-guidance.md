# Adaptive LLM-guided query planning — session-handoff notes

Framing notes for the OWASP-IL-2026 slide that carries the *architectural*
claim (companion to `demo/formbricks.md`, which carries the quantitative
sibling-recall claim). This is the "claim for fame" of dhscanner : the
scanner isn't just an LLM helping author Prolog rules offline, it's an
LLM *inside the query loop* that adapts exploration in real time based
on solve-time feedback.

Captured from the working session that landed the capability-verifier
predicate + `kb_called_from` gap fix (runner PR #62). Should end up
either on a slide, in the speaker notes, or explicitly parked with a
reason for skipping.

## The claim for fame — one paragraph

Deductive engines have historically been either fixed-plan-indexed (fast
but rigid — you commit to a query plan at compile time), or equipped
with a cost-based optimizer that plans against **schema statistics**
(still blind to *what the question means*). An LLM agent sitting inside
the query loop is a third animal : a planner whose input is (a) the
security question being asked in natural language, (b) live solve-time
telemetry from the previous goals, (c) semantic knowledge about which
fact types are cheap or expensive on this shape of codebase. That
combination doesn't exist in classical deductive DBs. The agent can
decide *mid-query* : "the 2-hop expansion is blowing budget on this
monorepo — cut off, project the fact set to just the crypto-leaf
callables, retry as a 1-hop starting from the verifier side." That's a
semantically-informed, budget-aware replanning step no rule-based
optimizer can pull off, because it requires understanding what the
question is actually asking.

## The two LLM roles ( don't conflate )

The scanner uses LLMs in two distinct places. Both matter, but only the
second is the "fame" claim.

| Axis            | Offline code-assist LLM                       | Adaptive online LLM agent                                   |
| --------------- | --------------------------------------------- | ----------------------------------------------------------- |
| Timescale       | hours – days                                  | ms – seconds per query                                      |
| Feedback signal | CI wall-time ( green / red )                  | live swipl solve-time per goal / subquery                   |
| Output          | source edits to `utils.pl`, kbgen walkers     | plan choices, timeouts, retries, projection sets            |
| Bound style     | *static* — designed into the predicate shape  | *dynamic* — negotiated per question per KB                  |
| Where it runs   | in the contributor's IDE ( or CI review bot ) | inside the runner's `--with_agent` loop, per formbricks scan |

The offline role gives you **statically-shaped predicates that are safe
by design**. The online role gives you **dynamically-bounded execution
that is safe regardless of design**. They compose — and it's the second
that carries the "KB can grow arbitrarily" claim.

## Why classical deductive-DB planners can't do this

Three-animal contrast, in one line each :

1. **Fixed-plan indexed** ( vanilla Prolog / Datalog ) : commit to a
   query plan at compile time. Fast on the intended shape ; brittle
   when the fact-count distribution changes.
2. **Cost-based optimizer** ( SQL query planners, some Datalog engines ) :
   plan against schema statistics. Better ; still doesn't know that
   *this particular question* is about capability-gated storage
   endpoints and therefore the crypto-leaf catalog is the sensible
   starting point.
3. **LLM agent in the query loop** : combines (a) natural-language
   understanding of the question, (b) real-time solve-time telemetry,
   (c) semantic priors about which fact types are cheap vs expensive
   on this shape of codebase. Chooses the starting predicate, budget,
   and reformulation strategy accordingly.

## KB growth strategy — static + dynamic compose

Every session we add facts, kb grows, and in principle this can blow up
query time. The **static** discipline ( offline role ) minimizes worst
case ; the **dynamic** discipline ( online role ) actually bounds it.

Static, in `utils.pl` :

- Every new `kb_*` fact type is classified by growth order at design
  time : per-file ( few ), per-callable ( moderate ), per-call-site
  ( many ), per-instruction ( very many ).
- The top of every `utils_*` clause is either a **name-catalog gate**
  ( `utils_capability_verifier_name/1`, `utils_authenticating_function_name/1`,
  ... — ground clauses at the leaves ) or a **file-marker anchor**
  ( `sub_atom(F, _, _, _, 'apps_slash_...')` — pins the search to a
  known atom prefix ). That keeps the most-selective goal leftmost.
- Silent-failure audits : the LLM cross-checks every `kb_*` referenced
  in `utils.pl` against the kbgen source. The recent `kb_called_from`
  fix is exactly this — the fact type had been declared in
  `dhscanner-kbgen` for a long time, referenced by six `utils.pl`
  predicates, but no service walker emitted it ; six queries had been
  silently returning zero on real KBs until the new
  capability-verifier hop-predicate assertion in CI ( runner PR #62 )
  surfaced it.
- CI as empirical ground truth : `tests.yaml` runs the full formbricks
  scan on every PR and asserts specific `MATCH:` outputs from swipl
  queries. Solve-time is implicitly measured by GitHub Actions step
  timing.

Dynamic, in the runner's `--with_agent` loop :

- Solve-time telemetry per goal is a first-class signal ; the agent
  reads it and reshapes the next query.
- Per-question budget : the agent decides *how much query time* is
  worth spending on a given security question, and it can trade
  completeness for bound when the KB is large.
- Mid-query replanning : cut, project the fact set to a smaller subset
  ( eg only crypto-leaf callables ), or start from a different
  predicate entirely.

The claim isn't "the LLM proves the query stays bounded" ; it's "the
LLM negotiates cost against per-question budget in real time, so
unbounded queries get *actively reformulated* rather than *statically
prevented*". Growth becomes controlled because the runtime loop has
levers, not just because the compile-time predicates are well-shaped.

## Where the online agent lives today

Pointers into the current implementation, so the slide narrative can be
grounded ( not aspirational ) :

- CLI entry point : `python -m cli run --with_agent ...` ( see
  `.github/workflows/tests.yaml`, formbricks scan step ).
- Agent-mode behaviour is documented in `tests.yaml` :
  "analysis stops after the queryengine has written the KB ; no SARIF
  is produced. The CLI logs the KB path as
  `[ step 6 ] kb filename: /tmp/kb_XXX.pl`, which the next step feeds
  straight into `docker compose cp` to grep the facts."
- What "step 6" hands off *to* is where the online agent guides
  exploration : that's the load-bearing loop for the fame claim.

## Where the fame demo goes from here

Once the URL-redirect-pool feature closes ( the "last gap" ), the OWASP
slide can literally show a live agent trace against formbricks :

1. Show the natural-language question the agent starts with
   ( eg "which storage endpoints are capability-gated versus
   independently discoverable ?" ).
2. Show the first Prolog subgoal it chose and its solve-time.
3. Show the reformulation it made based on the observed cost.
4. Show the final verdict, contrasted with a fixed-plan run that
   would have burned the whole budget on the wrong starting point.

Anecdote-driven slide > architecture-diagram slide. The point is *not*
"here is our pipeline" ; the point is "here is the LLM guiding
exploration, in real time, and here is the cost bound it enforced".

## Design invariants to preserve

Short list an OWASP-audience reader ( or a future iterator ) can carry
away without reading the code :

1. Every new fact type is classified by growth order at design time.
2. Top-of-clause is always a name-catalog gate or a file-marker anchor.
3. Predicates that reference a `kb_*` are cross-audited against the
   kbgen source to catch silent-failure gaps ( `kb_called_from`-style ).
4. CI-visible `MATCH:` assertions guard both correctness and,
   implicitly, solve-time regression.
5. The `--with_agent` runtime loop is the load-bearing bound on KB
   growth cost. Anything that breaks its ability to observe or
   reformulate is a fame-claim regression, not a performance nit.
