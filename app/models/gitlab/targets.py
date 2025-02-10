from enum import Enum


# all possible targets for the public arcs endpoint
class Targets(str, Enum):
    tübingen = "tuebingen"
    freiburg = "freiburg"
    plantmicrobe = "plantmicrobe"
    testenv = "tuebingen_testenv"
    fdat = "fdat"
