# Phase 8 vocabulary attribution

The vocabulary index combines two documented sources:

* **FinnWordNet 2.0** — https://www.kielipankki.fi/download/FinnWordNet/v2.0/FinnWordNet-2.0.zip
  * Finnish lexical meanings and part-of-speech data.
  * License: Princeton WordNet license + Creative Commons Attribution 3.0.
  * Preserve the WordNet 3.0 Princeton copyright notice and the University of
    Helsinki attribution when redistributing the archive or derived data.
* **UD Finnish-TDT and UD Finnish-FTB**, through the Phase 3 processed corpus —
  https://universaldependencies.org/treebanks/fi_tdt/index.html and
  https://universaldependencies.org/treebanks/fi_ftb/index.html
  * Observed forms, UD POS/features, frequencies, and selected corpus examples.
  * Licenses: TDT CC BY-SA 4.0; FTB CC BY 4.0.

The index does not generate a complete Finnish paradigm and does not use an LLM
as a dictionary source. The generated JSONL is a corpus-bounded lookup artifact;
its manifest records the input hashes and source metadata. FinnWordNet meanings
are unranked sense candidates, and translation entries marked as approximate,
broader, narrower, unconfirmed, or otherwise qualified are excluded. Multiple
UD morphology analyses for one observed form remain visible with their counts.
