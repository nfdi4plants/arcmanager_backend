import pandas as pd
from json import loads
import numpy as np
import os
from pathlib import Path
import datetime


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
            isaFile = pd.read_excel(path, 0)

        # if none matches, just read the file with default values

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
            isaFile = pd.read_excel(pathName, sheet_name=sheetName2)
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

    # if there is just one column, add a second one to make space for a date
    if isaFile.shape[1] < 3:
        isaFile.insert(2, "Unnamed: 2", "")

    # insert the current date next to the identifier to indicate the date since the metadata was last edited
    isaFile.iat[identifierLocation, 2] = datetime.date.today().strftime("%d/%m/%Y")
    # save the changes to the excel file
    isaFile.to_excel(
        pathName,
        sheet_name=sheetName,
        merge_cells=False,
        index=False,
    )
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


# currently in development; usage is to extend the investigation file everytime a new study is created
async def appendStudy(pathToInvest: str, pathToStudy: str):
    study = pd.read_excel(pathToStudy, sheet_name="Study")
    print(study)
    invest = pd.read_excel(pathToInvest)
    print(invest)
    extended = pd.concat([invest, study], ignore_index=True)

    print(extended)

    extended.to_excel(pathToInvest, merge_cells=False, index=False)


def getSwateSheets(path: str, type: str):
    excelFile = pd.ExcelFile(path)
    sheets = []
    names = []
    match type:
        case "study":
            sheetNames = excelFile.sheet_names

            for x in sheetNames:
                if x != "Study" and x != "isa_study":
                    swateSheet = pd.read_excel(path, sheet_name=x)
                    sheets.append(loads(swateSheet.to_json(orient="split")))
                    names.append(x)

        case "assay":
            sheetNames = excelFile.sheet_names

            for x in sheetNames:
                if x != "Assay" and x != "isa_assay":
                    swateSheet = pd.read_excel(path, sheet_name=x)
                    sheets.append(loads(swateSheet.to_json(orient="split")))
                    names.append(x)
    return sheets, names


def createSheet(tableHead, tableData, path: str, id, target: str, name: str):
    data = {}
    for i, entry in enumerate(tableHead):
        columnData = []
        for cell in enumerate(tableData[i]):
            columnData.append(cell[1])
        data[str(entry["Type"])] = columnData

    df = pd.DataFrame(data)

    pathName = os.environ.get("BACKEND_SAVE") + target + "-" + str(id) + "/" + path

    print(df)

    with pd.ExcelWriter(
        pathName, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        df.to_excel(writer, sheet_name=name, merge_cells=False, index=False)


def readSheet(name: str, path: str, type: str):
    excelFile = pd.ExcelFile(path)
