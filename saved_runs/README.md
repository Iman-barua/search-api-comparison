Place exported run JSON files here to make them available in the run library and on the
landing page.

No fabricated API outputs ship with this project. Run each company, inspect the evidence,
generate assessments, then export the providers whose plans permit storage.

Before committing anything here:

    python validate_saved_runs.py

It opens every file the way the app does, reports company, window, policy version, context
version and per-provider verdicts, warns on credential-like strings, and exits non-zero if
any file is unreadable. Also confirm each file is free of private data and that your plan
grants storage and sharing rights for every provider it contains. Brave requires explicit
storage rights and is excluded from exports by default.

Runs exported before version 2.0 still open, but they carry no Linkup context version and
no fit verdicts, so the run library will flag them as not comparable with newer runs.
