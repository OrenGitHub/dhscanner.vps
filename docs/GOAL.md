# GOAL

## Overview

Dhscanner is an open-source, cross-file, inter-procedural static
analyzer. It was first presented publicly at [OWASP IL 2025][1].
That presentation introduced an objective paradigm for comparing SAST scanners.
We collected dozens of real-life CVEs and their fixes, and gave an in-depth
description of the algorithmic aspects needed by static code analyzers to
identify the vulnerability, and *not* issue a false alarm on the fix.
We made sure to emphasize that dhscanner too has clear limits:
revealing where it missed true positives, and where false alarms were
issued on proper fixes. But something else bothered us - timeouts.
This issue was not addressed in the OWASP 2025 conference, but
it was a real pain. To the best of our knowledge, companies scanning their
code bases do it with a predefined list of vulnerabilities they look for.
Sure, critical flaws are tested first, but given a time budget, every scan
will need to prioritize its exploration area. Then it hit us - we should expose our knowledge
base through a dedicated API and let LLMs drive exploration.
Modern language models bring broad security knowledge to the loop,
and can incrementally shift their focus based on what they have already found.

## Next Step: [OWASP IL 2026][2] ( October )

Our main task was designing an effective API over the existing knowledge base.
We approached this task thinking of a human pen tester doing black box evaluation -
what will be their first steps? enumerate endpoints? aim for pre-auth flaws initially?
what might they be missing without the underlying source code? query params? hidden routes?
Defining the API meant carefully formulating a *semantic layer* on top of the knowledge base
in a way that is both expressive and concise. Inspired by real-life open-source applications,
we tuned the semantic layer through trial and error. At times it felt more art than science.
Still, as mileage was beginning to accumulate, some core concepts started to emerge.

### Programming-language independence

The language and web framework (Ruby/Rails, Python/Django, or JavaScript/Express) are
captured *inside* the knowledge base itself, so the query interface stays completely
agnostic to the target's stack.

### Time-bounded queries

Static analysis involves many queries that traverse transitive closures, which can take
a long time to resolve. From very early on it was clear that meaningful prioritization is
only possible if every query respects a configurable upper time bound.

## Current phase ( July - October 2026 )

We implemented our approach and started scanning open-source applications.
We found a new code vulnerability in a highly starred TypeScript repo
( [formbricks][3] ) acknowledged by the maintainers, and [fixed upstream][4].
In the coming months, we want to prove *general applicability* of the paradigm
on *more* real-world applications listed on [HackerOne bug bounty programs][5].

---

*When this goal is met, this file is rewritten with the next
north-star goal. Do not accumulate history here; use the git log.*

[1]: https://www.linkedin.com/posts/oren-ish-shalom-68156649_owasp-activity-7336662148623863810-MLCV?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAo6HkEB0cRPObPntw8KqfRC0B5Ae-TRYOw
[2]: https://appsecil.org/
[3]: https://github.com/formbricks/formbricks
[4]: https://github.com/formbricks/formbricks/releases/tag/4.0.0
[5]: https://hackerone.com/opportunities/all/search?asset_types=SOURCE_CODE&ordering=Newest+programs