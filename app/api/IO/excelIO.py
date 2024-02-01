import pandas as pd
from json import loads
import numpy as np
import os
from pathlib import Path
import datetime
from fastapi import HTTPException
import openpyxl


# reads out the given file and sends the content as json back
def readIsaFile(path: str, type: str):
    # initiate isaFile structure
    isaFile: pd.DataFrame

    # match the correct sheet name with the given type of isa
    match type:
        case "investigation":
            sheetName = "isa_investigation"

        case "study":
            sheetName = "Study"

            # the intended name stated in the arc specification
            sheetName2 = "isa_study"

        case "assay":
            sheetName = "Assay"

            # the intended name stated in the arc specification
            sheetName2 = "isa_assay"
        case other:
            sheetName = sheetName2 = ""

    # read the file
    try:
        isaFile = pd.read_excel(path, sheet_name=sheetName)
    except:
        try:
            isaFile = pd.read_excel(path, sheet_name=sheetName2)
        except:
            # if none matches, just read the file with default values
            isaFile = pd.read_excel(path, 0)

    # parse the dataframe into json and return it
    parsed = loads(isaFile.to_json(orient="split"))

    return parsed


# replaces the old content of the file with the new content
def writeIsaFile(
    path: str, type: str, id: int, oldContent, newContent, repoId: int, location: str
):
    # construct the path with the given values (e.g. .../freiburg-33/isa.investigation.xlsx)
    pathName = f"{os.environ.get('BACKEND_SAVE')}{location}-{repoId}/{path}"
    identifierLocation = 5

    # match the correct sheet name with the given type of isa
    match type:
        case "investigation":
            sheetName = "isa_investigation"

        case "study":
            sheetName = "Study"

            # the intended name stated in the arc specification
            sheetName2 = "isa_study"
            identifierLocation = 0

        case "assay":
            sheetName = "Assay"

            # the intended name stated in the arc specification
            sheetName2 = "isa_assay"
            identifierLocation = 0

        case other:
            sheetName = sheetName2 = ""

    # read the file
    try:
        isaFile = pd.read_excel(pathName, sheet_name=sheetName)
    except:
        try:
            sheetName = sheetName2
            isaFile = pd.read_excel(pathName, sheet_name=sheetName2)
        except:
            sheetName = 0
            isaFile = pd.read_excel(pathName, 0)

    # replace nan values with empty strings
    isaFile = isaFile.fillna("")

    # Here we replace every entry in the corresponding field with the new value (column by column)
    for x in range(1, len(newContent)):
        # if there are new fields in newContent insert a new column "Unnamed: number" with empty fields
        if x > len(oldContent) - 1:
            try:
                isaFile.insert(x, "Unnamed: " + str(x), "")
            except:
                isaFile.insert(x, "Unnamed")
            # add the new field to old content to extent its length
            oldContent.append("")

        # get the name of the current column
        columnName = isaFile[id : id + 1].columns[x]

        # read out the value on the row with the given id and the current column and replace it with the new value
        isaFile[id : id + 1].at[id, columnName] = (
            isaFile[id : id + 1]
            .at[id, columnName]
            .replace(oldContent[x], newContent[x])
        )

    # if there is just one column, add a second one to make space for a date
    if isaFile.shape[1] < 3:
        isaFile.insert(2, "Unnamed: 2", "")

    # insert the current date next to the identifier to indicate the date since the metadata was last edited
    isaFile.iat[identifierLocation, 2] = datetime.date.today().strftime("%d/%m/%Y")
    # save the changes to the excel file
    with pd.ExcelWriter(
        pathName, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        isaFile.to_excel(writer, sheet_name=sheetName, merge_cells=False, index=False)

    # return the name of the row back
    return isaFile.iat[id, 0]


# help function to figure out what isa file we are editing (for the sheet name)
def getIsaType(path: str):
    # split the path into an array with "/" as the separator
    pathSplit = path.split("/")

    # take the top entry of the array
    fileName = pathSplit.pop()

    # check if the file is starting with "isa" and ending with "xlsx"
    if fileName[:3] == "isa" and fileName[-4:] == "xlsx":
        # return the type of the isa
        return fileName.split(".")[1]
    else:
        return ""


# returns a list of all the non metadata sheets and their names
def getSwateSheets(path: str, type: str):
    excelFile = pd.ExcelFile(path)
    sheets = []
    names = []
    match type:
        case "study":
            sheetNames = excelFile.sheet_names

            # if the sheetName is not "Study" or "isa_study", then its a swate sheet
            for x in sheetNames:
                if x != "Study" and x != "isa_study":
                    swateSheet = pd.read_excel(path, sheet_name=x)
                    sheets.append(loads(swateSheet.to_json(orient="split")))
                    names.append(x)

        case "assay":
            sheetNames = excelFile.sheet_names

            # if the sheetName is not "Assay" or "isa_assay", then its a swate sheet
            for x in sheetNames:
                if x != "Assay" and x != "isa_assay":
                    swateSheet = pd.read_excel(path, sheet_name=x)
                    sheets.append(loads(swateSheet.to_json(orient="split")))
                    names.append(x)
    return sheets, names


# fill a new table column wise with the given data and safe it to the excel file
def createSheet(tableHead, tableData, path: str, id, target: str, name: str):
    head = []
    content = []

    # loop column by column
    for i, entry in enumerate(tableHead):
        columnData = []
        # loop row by row
        for cell in enumerate(tableData[i]):
            columnData.append(cell[1])

        head.append(str(entry["Type"]))
        content.append(columnData)
    df = pd.DataFrame({head[0]: content[0]})
    head.pop(0)
    content.pop(0)

    for i, entry in enumerate(head):
        df.insert(i + 1, entry, content[i], allow_duplicates=True)

    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{id}/{path}"

    # save data to file
    with pd.ExcelWriter(
        pathName, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        df.to_excel(writer, sheet_name=name, index=False)

    wb = openpyxl.load_workbook(filename=pathName)
    tab = openpyxl.worksheet.table.Table(
        displayName="annotationTable" + name,
        ref=f"A1:{openpyxl.utils.get_column_letter(df.shape[1])}{len(df)+1}",
    )
    style = openpyxl.worksheet.table.TableStyleInfo(
        name="TableStyleMedium11",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=True,
    )
    tab.tableStyleInfo = style
    wb[name].add_table(tab)
    wb.save(pathName)


# when you sync an assay to a study, either overwrite existing data or append new data
def appendAssay(pathToAssay: str, pathToStudy: str, assayName: str):
    # parse the correct sheet (first 8 rows for assay files)
    try:
        assay = pd.read_excel(pathToAssay, sheet_name="isa_assay").head(8)
    except:
        try:
            assay = pd.read_excel(pathToAssay, sheet_name="Assay").head(8)
        except:
            assay = pd.read_excel(pathToAssay, 0).head(8)

    try:
        study = pd.read_excel(pathToStudy, sheet_name="isa_study")
        sheetName = "isa_study"
    except:
        try:
            study = pd.read_excel(pathToStudy, sheet_name="Study")
            sheetName = "Study"
        except:
            study = pd.read_excel(pathToStudy, 0)
            sheetName = ""

    # fill nan with empty strings
    assay = assay.fillna("")
    study = study.fillna("")

    # find row containing the assay data in the study file
    try:
        assayIndex = (
            study.index[study["STUDY METADATA"] == "STUDY ASSAYS"].to_list()[0] + 1
        )
    except:
        raise HTTPException(
            status_code=400,
            detail="Study has no STUDY ASSAYS field",
        )

    # the number of columns
    columnLength = len(study.columns.to_list())

    # if there is just one column, add a second one to make space for the assay data
    if columnLength == 1:
        study["Unnamed: 1"] = ""

    # index of the free column
    freeColumn = 0

    # set to true if the same assay is already in the study
    overwrite = assayName in study.iloc[[assayIndex + 7]].to_string()

    # check for a free column
    for x in range(1, columnLength):
        # if assay already exits, get the column index
        if overwrite:
            if assayName in study.iat[assayIndex + 7, x]:
                freeColumn = x
                break

        # check the ASSAY FILE NAME Field for free space to insert the new assay
        elif study.iat[assayIndex + 7, x] == "":
            freeColumn = x
            break

    # if there is no free column add a new empty column
    if freeColumn == 0:
        freeColumn = len(study.columns)
        study["Unnamed: " + str(freeColumn)] = ""

    # fill the column with the assay data
    for x in range(len(assay)):
        study.iat[assayIndex + x, freeColumn] = assay.iat[x, 1]

    # make space for the date if there are just two columns
    if len(study.columns) < 3:
        study["Unnamed: 2"] = ""

    # insert the current date next to the identifier to indicate the date since the metadata was last edited
    study.iat[0, 2] = datetime.date.today().strftime("%d/%m/%Y")
    # save the changes to the excel file
    with pd.ExcelWriter(
        pathToStudy, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        study.to_excel(writer, sheet_name=sheetName, merge_cells=False, index=False)

    return study.to_json()


# append study to investigation file
def appendStudy(pathToStudy: str, pathToInvest: str, studyName: str):
    # parse the correct sheet
    try:
        invest = pd.read_excel(pathToInvest, sheet_name="isa_investigation")
        sheetName = "isa_investigation"
    except:
        invest = pd.read_excel(pathToInvest, 0)
        sheetName = ""

    try:
        study = pd.read_excel(pathToStudy, sheet_name="isa_study")
    except:
        try:
            study = pd.read_excel(pathToStudy, sheet_name="Study")
        except:
            study = pd.read_excel(pathToStudy, 0)

    # fill nan with empty strings
    invest = invest.fillna("")
    study = study.fillna("")

    # get a list of all rows named "Study Identifier"
    try:
        studyIndex = invest.index[
            invest["ONTOLOGY SOURCE REFERENCE"] == "Study Identifier"
        ].to_list()
    except:
        raise HTTPException(
            status_code=400, detail="Investigation file has no Study Identifier"
        )

    # index of the row containing the already existing study/the next free available row
    rowIndex = 0

    # find the right row index (first check if study is already there, or take the next free space)
    for x in studyIndex:
        if studyName in invest.iloc[[x]].to_string().replace(" ", ""):
            rowIndex = x
            break
        # check for free space, but prefer already exiting study
        if invest.iloc[x, 1] == "" and rowIndex == 0:
            rowIndex = x

    # if the study contains more columns, then extend the investigation file by the amount of missing columns
    if len(invest.columns) < len(study.columns):
        for x in range(len(study.columns) - len(invest.columns)):
            invest["Unnamed: " + str(len(invest.columns) + x)] = ""

    # if the study is not yet in the investigation file and there is also no free space, append a new empty study and fill it with the data
    if rowIndex == 0:
        # get a sample of an empty study
        emptyStudy = pd.read_excel(
            os.environ.get("BACKEND_SAVE") + "isa_files/isa.study.xlsx"
        )

        # rename the first column to match the column name of the investigation file (or else it will be added as a new column)
        emptyStudy.rename(
            columns={"STUDY METADATA": "ONTOLOGY SOURCE REFERENCE"}, inplace=True
        )
        # the index of the row to start is at the bottom of the invest file
        rowIndex = len(invest) + 1

        # add the row "STUDY" to indicate a new study
        invest.loc[len(invest)] = {"ONTOLOGY SOURCE REFERENCE": "STUDY"}

        # add the empty study to the investigation file
        invest = pd.concat([invest, emptyStudy], ignore_index=True)

    # finally fill the data in the correct rows
    for x in range(len(study)):
        for y in range(len(study.columns)):
            invest.iat[rowIndex + x, y] = study.iat[x, y]

    # make space for the date if there are just two columns
    if len(invest.columns) < 3:
        invest["Unnamed: 2"] = ""

    # insert the current date next to the identifier to indicate the date since the metadata was last edited
    invest.iat[5, 2] = datetime.date.today().strftime("%d/%m/%Y")
    # save the changes to the excel file
    with pd.ExcelWriter(
        pathToInvest, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        invest.to_excel(writer, sheet_name=sheetName, merge_cells=False, index=False)

    return invest.to_json()
