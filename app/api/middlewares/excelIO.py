import pandas as pd
from json import loads
import numpy as np
import os
from pathlib import Path


# reads out the given file and sends the content as json back
def readIsaFile(path: str, type: str):
    # initiate isaFile structure
    isaFile: pd.DataFrame

    # match the file to access the correct sheet
    match type:
        case "investigation":
            try:
                isaFile = pd.read_excel(path, sheet_name="isa_investigation")
            except:
                isaFile = pd.read_excel(path, 0)
        case "study":
            try:
                isaFile = pd.read_excel(path, sheet_name="Study")
            except:
                isaFile = pd.read_excel(path, 0)
        case "assay":
            try:
                isaFile = pd.read_excel(path, sheet_name="Assay")
            except:
                isaFile = pd.read_excel(path, 0)

        # if none matches, just read the file with default values
        case other:
            isaFile = pd.read_excel(path)

    # parse the dataframe into json and return it
    parsed = loads(isaFile.to_json(orient="split"))

    return parsed


# replaces the old content of the file with the new content
def writeIsaFile(
    path: str, type: str, id: int, oldContent, newContent, repoId: int, location: str
):
    # construct the path with the given values (e.g. .../freiburg-33/isa.investigation.xlsx)
    pathName = (
        os.environ.get("BACKEND_SAVE") + location + "-" + str(repoId) + "/" + path
    )

    # match the correct sheet name with the given type of isa
    match type:
        case "investigation":
            sheetName = "isa_investigation"

        case "study":
            sheetName = "Study"

        case "assay":
            sheetName = "Assay"

        case other:
            sheetName = ""

    # read the file
    try:
        isaFile = pd.read_excel(pathName, sheet_name=sheetName)
    except:
        isaFile = pd.read_excel(pathName, 0)

    # replace nan values with empty strings
    isaFile = isaFile.fillna("")

    # Here we replace every entry in the corresponding field with the new value (column by column)
    for x in range(1, len(newContent)):
        # if there are new fields in newContent insert a new column "Unnamed: number" with empty fields
        if x > len(oldContent) - 1:
            isaFile.insert(x, "Unnamed: " + str(x), "")
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
        # save the changes to the excel file
        isaFile.to_excel(
            pathName,
            sheet_name=sheetName,
            merge_cells=False,
            index=False,
        )

    # return the fully overwritten row back (currently unused, you could return anything)
    return isaFile[id : id + 1]


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


# currently in development; usage is to extend the investigation file everytime a new study is created
def appendStudy(pathToInvest: str):
    study = pd.read_excel(str(Path.cwd()) + "/app/api/middlewares/study.xlsx")

    invest = pd.read_excel(pathToInvest)

    extended = pd.concat([invest, study], ignore_index=True)

    print(extended)
