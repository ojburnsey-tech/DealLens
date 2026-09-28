# Test approach

The suite uses small independently calculated examples for each finance function.
Decimal comparisons are exact where the expected answer terminates; repeating results use Decimal division rather than rounded floating-point literals.
Inputs include explicit monetary scales so GBP/share, pence/share, absolute shares and millions of shares can be reconciled.

Research tests use temporary YAML files and in-memory or temporary DuckDB databases.
A deliberately removed `field_facts` table forces a database exception **after** the deal and sources are inserted; the test confirms rollback of every table.
Duplicate imports test that existing data remains unchanged and no new source rows leak into the database.

The independent finance review's reproductions require their own regression tests.
A passing baseline suite is not treated as proof that the engine is financially correct.
All Companies House tests must use mocked HTTP transports; no API key or live network is required to run the suite.
The real-deal test is a separate provisional source-reconciliation case until the owner completes manual verification.
