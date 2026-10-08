# P3DH extraction notes

## Method

The EDAP P3DH Data Points report is an embedded Power BI report. A browser session sets the reference date and one template. Playwright captures the `QueryExecution` request: the URL, the headers (with the token), and the JSON body. The downloader then replays that request with plain HTTP and changes only the filters.

The browser must open the EDAP landing page before the report page. Otherwise the portal can return HTTP 403.

## Response format

A response contains a tree of nested groups (`DM0` to `DM12`). Each level holds one dimension:

| Level | Dimension |
|-------|-----------|
| G0 | Entity code (LEI) |
| G1 | Entity name |
| G2 | Country |
| G3, G4 | Module name, module code |
| G5 | Cell code, for example `{K_61.00, r0050, c0010}` |
| G6 | Key descriptor (open tables) |
| G7 | Template |
| G8, G9 | Row code, row label |
| G10, G11 | Column code, column label (for example `a. T`, `b. T-1`) |
| G12 | Sheet (for example `Disclosure period T-3`) |
| M0 | Fact value |

The reference date is in the header (`SH`, `G13`). The query descriptor maps each `G<n>` to its field name.

Compression rules:

- A node can carry `R`, a bit mask. A set bit means that the value is the same as in the previous node at the same level.
- A node can carry a null mask. A set bit means that the value is null.
- A leaf item `{"R": 1}` means that the measure equals the previous measure.
- A dictionary-encoded value is an index into `ValueDicts`. A column schema (`S`) names the dictionary (`DN`).
- A number in a variant column is a string with a suffix, for example `7333000000D`.
- A text value is a quoted string, for example `'Quarterly'`.

`modules/fetch/dsr_decode.py` implements these rules. It walks the tree in document order and keeps the last value of each column.

## Limits and paging

The captured query has `Primary.Window.Count = 100` and `Secondary.Top.Count = 100`. Power BI computes the product of all counts. If the product is more than 25 million, it ignores the counts and returns only 500 rows (warning `SpecifiedReductionAlgorithmsExceedsMaxIntersections`).

If `Secondary.Top.Count` is 1, Power BI honours a primary window of 30000 rows. A window of 40000 rows is ignored. The downloader uses 30000.

A truncated response carries a restart token (`RT`). The downloader sends the token back in `Primary.Window.RestartTokens` and repeats until a response has no token. A page boundary repeats the last entity group, so the downloader drops the repeated facts.

Paging needs no entity list. A cross-check re-fetches a few entities by name and compares their facts with the paged result. The manifest records the result.

If paging fails, the downloader splits the entity list into batches. A batch with a truncated response is split in halves. A single entity that is still truncated marks the template `partial`.

## Entity identity

One LEI can appear under two names. Examples: a bank that was renamed after an acquisition, and two reporting entities of one group. Within one date, the pair (LEI, name) identifies a reporting entity. The same fact key under the same LEI but a different name has different values.

## Discovery

The portal slicers list reference dates, templates, and entities. These lists are virtual lists, so the code scrolls them. Template discovery is strict. It must not fall back to a stored list.

A stored list of template names was cut at 70 characters. A run that used it asked for template names that do not exist. Those queries ran until they timed out, and the run recorded them as "Query execution failed".

The entity list can miss entities. Paging does not depend on it.

## Defects of the first version (fixed)

These defects were found on 2026-10-08. Files that were downloaded before that date were incomplete. They are not in this repository.

1. The parser ignored the repeat mask. About 27% of the facts were dropped (repeated values, many of them zeros). Some entities that had only repeated values were dropped completely.
2. The parser used a fixed column map from an older model. The row, column, and column name fields held the wrong dimensions, and the exact cell code was lost.
3. The normaliser dropped all text facts (narratives, dates, booleans, reporting frequencies).
4. Template discovery fell back to a stored list with cut names (see above).
5. All counts were set to 5000. Power BI ignored them and returned 500 rows per request. This is why the first version split every template by entity.
6. An entity with a restart token could be dropped without an error, and the template was still marked `complete`.
7. The loader keyed facts by LEI only. This merged two reporting entities that share an LEI.

## Open item

The query for `K_83.01` (EU CQ4) fails on the server. After 225 seconds the portal answers HTTP 200 with an error body (`rsQueryTimeoutExceeded`, "The XML for Analysis request timed out... Timeout value: 225 sec"). This happens even for one entity (tested for NBG on 30/06/2026). The error body has the key `DataShapes`, not `DS`. The decoder raises `ResponseError` for it.

Dates that list `K_83.01`: 31/12/2025 and 30/06/2026. The downloader skips it (status `skipped_slow`) unless you pass `--include-slow`. That option raises the request timeout to 300 seconds so that the server error can arrive.

## Checks that the downloader and the verifier run

- Each response must have the requested reference date and template.
- The decoder raises an error if a repeat bit has no earlier value, or if a dictionary reference cannot be resolved. All 278 stored archives decode without such an anomaly.
- A paged result is compared with a fresh request for a sample of entities. The sample includes the entities where a page was cut.
- `scripts/verify_p3dh.py` decodes the raw archives again and compares them with the CSV files. It also compares the reported KM1 capital ratios with capital divided by RWEA (98.9% to 99.9% of the cells agree).
