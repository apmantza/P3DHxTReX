Backlog

- P3DH API parser: handle alternate response shape for `K_83.01 - EU CQ4: Quality of non-performing exposures by geography`.
- `K_83.01` currently times out with the generic replay query and needs a dedicated fallback query strategy.
- The attempted partition-by-entity workaround is not stable enough to ship because the visible entity list can vary with slicer state.
- Keep the 88-template automated path unchanged; any `K_83.01` work must remain isolated from the stable downloader.
