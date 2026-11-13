# Clip: Castro & Liskov, *Practical Byzantine Fault Tolerance* (OSDI 1999)

- **URLs:** https://pmg.csail.mit.edu/papers/osdi99.pdf (unavailable at capture) · https://en.wikipedia.org/wiki/Practical_Byzantine_fault_tolerance
- **Authors:** Miguel Castro, Barbara Liskov (MIT)
- **Date:** OSDI 1999; extended version ACM TOCS 2002 ("PBFT and Proactive Recovery")
- **Captured:** November 2026 (summary of the published paper and its Wikipedia article; the PDF was unavailable at capture)

## Key facts
- State machine replication tolerant of Byzantine faults (replicas that lie, omit or act arbitrarily), practical on asynchronous networks such as the internet.
- **Classic bound:** n ≥ 3f + 1 replicas tolerate f faulty ones. Quorums of 2f + 1 guarantee that any two quorums intersect in at least one honest replica.
- A three-phase protocol (pre-prepare, prepare, commit), a view change when the primary fails, and periodic **checkpoints** that become stable with 2f + 1 signatures, allowing the old log to be discarded.
- Safety does not depend on synchrony; liveness requires eventual synchrony.
- Wikipedia: the general requirement for Byzantine fault tolerance is at least 3F+1 participants for F faults.
