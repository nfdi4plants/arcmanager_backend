# ARC validator concept

For now just some random notes. But if we have a concept, this can go here...

## Proposed implementation of arc-validate

[arc-validate](https://github.com/nfdi4plants/arc-validate) looks really promising! Maybe we should just incorporate it into our backend and somehow transform their output in something we can use

![image](https://github.com/nfdi4plants/arcmanager_backend/assets/133099925/db6455e2-944e-424e-863a-d97a0bc5010e)


## Notes

Testing parameters taken from https://github.com/nfdi4plants/arc-validate

### List of critical tests
- Is the .arc folder present?
- Are a .git folder and all related files and subfolders present?
- Is an Investigation file present?
- Does the investigation have an identifier?
- Does the Investigation have a title?
- Does at least one correctly registered person exist in the Investigation Contacts section?
- Does the ARC contain a top-level valid CWL (≥v1.2) file?
- Is the studies folder present?
- Does each Study in the studies folder have a Study file?
- Are all Studies present in the studies folder registered in the Investigation file?
- Do all Studies registered in the Investigation file have an identifier?
- Do all Studies registered in the Investigation file have a Study filepath?
- Are all Studies registered in the Investigation file present in the filesystem?
- Is the assays folder present?
- Does each Assay in the assays folder have an Assay file?
- Are all Assays present in the assays folder registered in the Investigation file and any Study file?
- Do all Assays registered in the Investigation file or any Study file have an identifier?
- Do all Assays registered in the Investigation file or any Study file have an Assay filepath?
- Are all Assays registered in the Investigation file or any Study file present in the filesystem?
- Is the workflows folder present?
- Does every Workflow contain a valid CWL (≥v1.2) file?
- Is the runs folder present?
- Does every Run contain a valid CWL (≥v1.2) file?
- Are all in the Annotation Tables described datafile paths present in the filesystem?

### List of non-critical tests
- Does any Study or Assay contain a Factor?
- Do all Annotation Tables have valid input (Source Name) and output (Sample Name, Raw Data File, Derived Data File) columns?
- Are all Annotation Table input and output columns filled out?
- Are all Annotation Table terms valid? (i.e., do they have valid TANs (Term Accession Numbers) and TSRs (Term Source REFs)?)
- Are community-specific data formats used? (i.e., mzML, mzTAB, fastq, fastq.gz, SAM, BAM)
