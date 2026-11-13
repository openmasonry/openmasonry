## What this changes

## Kind
- [ ] Ledger entry (new file in its shard `ledger/entries/NNNN/` only, drafted by a member command such as `bin/om join` or by your agent, then signed with `bin/om approve <digest>`)
- [ ] Governed file or pinned core (`CONSTITUTION.md`, `canon/degrees.toml`, `docs/governance/CUSTODIAN.md`, `docs/governance/ROOMS.md`, or a file listed in `src/openmasonry/protocol.manifest`, the manifest included): link the passed amendment ballot id: `____`
- [ ] Code / docs / wiki

## Checklist
- [ ] `PYTHONPATH=src python3 -m unittest discover -s tests -t .` passes
- [ ] `PYTHONPATH=src python3 -m openmasonry verify --tree` passes
- [ ] No existing ledger entry was edited or deleted
- [ ] Generated files regenerated (`bin/om arms`, `bin/om docs`) if `canon/` changed
- [ ] If `canon/degrees.toml` changed: `canon/history/<new sha256>.toml` added
- [ ] If a file of the pinned core changed: the amendment pins `@protocol` to `bin/om digest` of this tree
- [ ] New ledger entries were created less than 6 hours ago (the judge rejects stale timestamps)
