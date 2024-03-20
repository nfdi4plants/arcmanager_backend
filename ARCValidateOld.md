## From [old arc-validate project](https://github.com/nfdi4plants/arc-validate/tree/main) documentation

*Does not exist anymore like this, saved from past version*

### Filesystem tests

Treat ARC specification-related requirements on ARCs regarding filesystem structure (i.e., the presence and content of specific files and folders).

**Filesystem**

### ISA tests

Cover both ARC specification as well as the ISA standard (in the form of ISA.NET requirements)

- **Schema**: Tests about the ISA schema format correctness. E.g.:
  - _Is there an investigation?_
- **Semantic**: Tests about semantic compliance to ARC specification. E.g.:
  - _Do all terms have identifiers?_
  - _Is the ARC CWL-compliant?_
- **Plausibility**: Tests about scientific plausibility. E.g.:
  - _Is there a Factor?_
  - _Does the ISA object make sense from a scientific point of view?_

### Critical tests

Critical tests are such that concern the primal integrity of the ARC. If these fail, the ARC's integrity is not given and thus does not satisfy the requirements (i.e., the ARC specification) on a basic level.
If any critical test fails, the validation returns an error exit code while this does not happen if all critical tests succeed.  

- Is the .arc folder present?
- Are a .git folder and all related files and subfolders present?
- ~~Is an Investigation file present?~~
- ~~Does the investigation have an identifier (ORCID)?~~
- ~~Does the Investigation have a title?~~
- Does at least one correctly registered person exist in the Investigation Contacts section? **?**
- Does the ARC contain a top-level valid CWL (≥v1.2) file? 
- ~~Is the studies folder present?~~
- Does each Study in the studies folder have a Study file?
- Are all Studies present in the studies folder registered in the Investigation file? **?**
- Do all Studies registered in the Investigation file have an identifier?
- Do all Studies registered in the Investigation file have a Study filepath?
- Are all Studies registered in the Investigation file present in the filesystem?
- ~~Is the assays folder present?~~
- Does each Assay in the assays folder have an Assay file?
- Are all Assays present in the assays folder registered in the Investigation file and any Study file?
- Do all Assays registered in the Investigation file or any Study file have an identifier?
- Do all Assays registered in the Investigation file or any Study file have an Assay filepath?
- Are all Assays registered in the Investigation file or any Study file present in the filesystem?
- ~~Is the workflows folder present?~~
- Does every Workflow contain a valid CWL (≥v1.2) file?
- Is the runs folder present?
- Does every Run contain a valid CWL (≥v1.2) file?
- Are all in the Annotation Tables described datafile paths present in the filesystem?

### Non-critical tests

Non-Critical tests revolve around best practices in ARC and ISA structure and annotation and describe the quality of an ARC. 

- Does any Study or Assay contain a Factor?
- Do all Annotation Tables have valid input (Source Name) and output (Sample Name, Raw Data File, Derived Data File) columns?
- Are all Annotation Table input and output columns filled out?
- Are all Annotation Table terms valid? (i.e., do they have valid TANs (Term Accession Numbers) and TSRs (Term Source REFs)?)
- Are community-specific data formats used? (i.e., mzML, mzTAB, fastq, fastq.gz, SAM, BAM)

### Missing?

- Firstname + Lastname ?
