import logging
import os
import time
from typing import Annotated
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    status,
    Response,
    Request,
    Header,
)
import requests

from app.api.endpoints.projects import getData, getTarget, writeLogJson
from app.models.gitlab.input import userContent
from app.models.gitlab.user import Users

router = APIRouter()

commonToken = Annotated[str, Depends(getData)]


# get a list of all users for the datahub
@router.get(
    "/getUser",
    summary="Get a list of all users",
    description="Gets a list of all registered users of the datahub",
    response_description="Array containing every possible user with details such as the id, name, avatar and more",
)
async def getUser(request: Request, token: commonToken) -> Users:
    startTime = time.time()
    try:
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getUser",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    userList = []
    users = requests.head(
        f"{os.environ.get(target)}/api/v4/users?per_page=100",
        headers=header,
    )
    try:
        pages = users.headers["x-total-pages"]
    except:
        writeLogJson(
            "getUser",
            404,
            startTime,
            "No users found! Reason: " + users.reason,
        )
        raise HTTPException(
            status_code=users.status_code,
            detail="No users found! Reason: " + users.reason,
        )

    for x in range(int(pages)):
        users = requests.get(
            f"{os.environ.get(target)}/api/v4/users?per_page=100&without_project_bots=true&page="
            + str(x + 1),
            headers=header,
        )
        try:
            userList += users.json()
        except:
            userList += {}

    logging.info(f"Sent list of all users of the datahub!")
    writeLogJson("getUser", 200, startTime)

    return Users(users=userList)


@router.post(
    "/addUser",
    summary="Adds a user to the project",
    status_code=status.HTTP_201_CREATED,
    description="Adds a user to your ARC with the given permission rights. There are a total of 5 different roles available and can be set through the 'role' parameter (number between 10-50, multiple of 10).",
    response_description="User {name} was added successfully!",
)
async def addUser(request: Request, userData: userContent, token: commonToken):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "addUser",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    # get the id and name of the user
    arcId = userData.id
    name = userData.username
    userId = userData.userId

    # look if the user role is set, else set it to 30 (developer)
    try:
        userRole = userData.role
    except:
        userRole = 30

    addRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{arcId}/members",
        headers=header,
        data=f"user_id={userId}&access_level={userRole}",
    )
    if not addRequest.ok:
        logging.error(f"Couldn't add user {name} ! ERROR: {addRequest.content}")
        writeLogJson(
            "addUser",
            400,
            startTime,
            f"Couldn't add user {name} ! ERROR: {addRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't add user to project! Error: {addRequest.content}",
        )
    logging.info(f"Added user {name} to project {arcId} with role {userRole}")
    writeLogJson("addUser", 201, startTime)

    return f"The user {name} was added successfully!"


# get a list of all users for the specific Arc
@router.get(
    "/getArcUser",
    summary="Get a list of all members of the arc",
    description="Gets a list of all users that have a membership in your ARC (have a role)",
    response_description="Array containing every ARC user with details such as the id, name, avatar and more",
)
async def getArcUser(
    request: Request, id: Annotated[int, Query(ge=1)], token: commonToken
) -> Users:
    startTime = time.time()
    try:
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getArcUser",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    # request to get all users for the specific arc
    users = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members?per_page=100",
        headers=header,
    )
    if not users.ok:
        try:
            userJson = users.json()
            userJson["error"] != None
        except:
            userJson = {"error": "Not found!", "error_description": "No user found!"}
        writeLogJson(
            "getArcUser",
            users.status_code,
            startTime,
            f"{userJson['error']}, {userJson['error_description']}",
        )
        raise HTTPException(
            status_code=users.status_code,
            detail=f"{userJson['error']}, {userJson['error_description']}",
        )

    logging.info(f"Sent list of users for project {id}")
    writeLogJson("getArcUser", 200, startTime)
    try:
        userList = users.json()
    except:
        userList = users.content

    return Users(users=userList)


# removes a user from the specific Arc
@router.delete(
    "/removeUser",
    summary="Removes a user from the project",
    description="Removes the user with the given id from your ARC member list",
    response_description="User {username} was removed successfully!",
)
async def removeUser(
    request: Request,
    id: Annotated[int, Query(ge=1)],
    userId: Annotated[int, Query(ge=1)],
    username: str,
    token: commonToken,
):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "removeUser",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    # request to delete the given user
    removeRequest = requests.delete(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members/{userId}",
        headers=header,
    )
    if not removeRequest.ok:
        logging.error(
            f"Couldn't remove user {username} ! ERROR: {removeRequest.content}"
        )
        writeLogJson(
            "removeUser",
            400,
            startTime,
            f"Couldn't remove user {username} ! ERROR: {removeRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't remove user from project! Error: {removeRequest.content}",
        )
    logging.info(f"Removed user {username} from project {id}")
    writeLogJson("removeUser", 200, startTime)

    return f"The user {username} was removed successfully!"


# edits the role of a user from the specific Arc
@router.put(
    "/editUser",
    summary="Edits a user of the project",
    description="Change the role of the given member of your ARC to the new role",
    response_description="User {name} was edited successfully!",
)
async def editUser(request: Request, userData: userContent, token: commonToken):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "editUser",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    id = userData.id
    userId = userData.userId
    username = userData.username
    role = userData.role

    # request to update user with given role
    editRequest = requests.put(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members/{userId}?access_level={role}",
        headers=header,
    )
    if not editRequest.ok:
        logging.error(f"Couldn't edit user {username} ! ERROR: {editRequest.content}")
        writeLogJson(
            "editUser",
            400,
            startTime,
            f"Couldn't edit user {username} ! ERROR: {editRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't edit user from project {id} to role {role}! Error: {editRequest.content}",
        )
    logging.info(f"Edited user {username} from project {id} to role {role}")
    writeLogJson("editUser", 200, startTime)

    return f"The user {username} was edited successfully!"


# returns a list of all groups the user is part of
@router.get(
    "/getGroups",
    summary="Get a list of the users groups",
    description="If you are member of a group in the datahub you will get an array containing all groups you are a part of",
    response_description="Array containing the name and id of every group you are a part of",
)
async def getGroups(request: Request, token: commonToken) -> list:
    startTime = time.time()
    try:
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
        # request arc studies
        groups = requests.get(
            f"{os.environ.get(target)}/api/v4/groups",
            headers=header,
        )

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getStudies",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found! Please authorize or refresh session!",
        )
    try:
        groupsJson = groups.json()
    except:
        raise HTTPException(
            status_code=groups.status_code,
            detail="Error retrieving the list of groups!",
        )
    if not groups.ok:
        raise HTTPException(status_code=groups.status_code, detail=groupsJson)

    writeLogJson("getStudies", 200, startTime)
    return [{"name": x["name"], "id": x["id"]} for x in groupsJson]
