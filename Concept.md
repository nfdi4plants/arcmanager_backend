# ARC validator concept

## DONE basic criteria

Do files/folders exist? (content doesn't matter for now)

- [x] investigation.xlsx (redundant)
- [x] assays
- [x] studies
- [x] workflows
- [x] runs
- [x] .arc

investigation.xlsx contents

- [x] Title ("Investigation Title")
- [x] Description ("Investigation Description")
- [x] Identifier ("Investigation Identifier")
- [x] Submission Date ("Investigation Submission Date")
- [x] Release Date ("Investigation Public Release Date")

## Implement Basic criteria

investigation.xlsx contents

- [ ] ORCID (optional) **Fields missing from investigation.xlsx**
- [x] Affiliation ("Investigation Person Affiliation")
- [x] At least one **contact** obligatory: Email ("Investigation Person Email") 
- [ ] Only if no email: A First and Last Name ("Investigation Person First Name"+"Investigation Person Last Name") also couple it to affiliation

> Discuss wether this implementation (email/name) is ok...

studies

> What to check?

assays

> What to check?

## Implement Advanced Criteria

Is everything (study, assay, ...) registered in investigation.xlsx?
