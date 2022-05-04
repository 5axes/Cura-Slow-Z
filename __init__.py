# Copyright (c) 2022 5@xes
# The SlowZ is released under the terms of the AGPLv3 or higher.

from . import SlowZ


def getMetaData():
    return {}

def register(app):
    return {"extension": SlowZ.SlowZ()}
