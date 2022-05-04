# Initial Copyright (c) 2020 Shane Bumpurs c/o fieldOfView
# Copyright (c) 2022 5@xes
#
# Based on an existing Plugin https://github.com/VMaxx/SlowZ
# The SlowZ is released under the terms of the AGPLv3 or higher.
#
# Description:  postprocessing script to slowdown the speed according to the Z height
#               https://marlinfw.org/docs/gcode/M220.html
#
#------------------------------------------------------------------------------------------------------------------------------------
#
#   Version 1.0 07/05/2022 Add slow down using M220 S(SlowDown%)
#------------------------------------------------------------------------------------------------------------------------------------

import re
from collections import OrderedDict

from UM.Extension import Extension
from UM.Application import Application
from UM.Settings.SettingDefinition import SettingDefinition
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Logger import Logger

def is_begin_layer_line(line: str) -> bool:
    """Check if current line is the start of a layer section.

    Args:
        line (str): Gcode line

    Returns:
        bool: True if the line is the start of a layer section
    """
    return line.startswith(";LAYER:")
  
def is_z_line(line: str) -> bool:
    """Check if current line is a Z line

    Args:
        line (str): Gcode line

    Returns:
        bool: True if the line is a Z line segment
    """
    return "G0" in line and "Z" in line and not "E" in line
        
class SlowZ(Extension):
    def __init__(self):
        super().__init__()

        self._application = Application.getInstance()

        self._i18n_catalog = None

        self._settings_dict = OrderedDict()
        self._settings_dict["slowz_percentage"] = {
            "label": "Slow Z percentage",
            "description": "Positive value to slow the print as the z value rises up to this percentage.",
            "type": "float",
            "unit": "%",
            "default_value": 0,
            "minimum_value": "0",
            "maximum_value_warning": "50",
            "resolve": "",
            "settable_per_mesh": False,
            "settable_per_extruder": False,
            "settable_per_meshgroup": False
        }
        self._settings_dict["slowz_height"] = {
            "label": "Slow Z height",
            "description": "Positive value to define the start height of the speed reduction.",
            "type": "float",
            "unit": "mm",
            "default_value": 50,
            "minimum_value": "0",
            "settable_per_mesh": False,
            "settable_per_extruder": False,
            "settable_per_meshgroup": False
        }
        self._settings_dict["slowz_enable"] = {
            "label": "Enable Slow Z",
            "description": "Activate Slow Z.",
            "type": "bool",
            "default_value": False,
            "settable_per_mesh": False,
            "settable_per_extruder": False,
            "settable_per_meshgroup": False
        }
        ContainerRegistry.getInstance().containerLoadComplete.connect(self._onContainerLoadComplete)

        self._application.getOutputDeviceManager().writeStarted.connect(self._filterGcode)


    def _onContainerLoadComplete(self, container_id):
        if not ContainerRegistry.getInstance().isLoaded(container_id):
            # skip containers that could not be loaded, or subsequent findContainers() will cause an infinite loop
            return

        try:
            container = ContainerRegistry.getInstance().findContainers(id = container_id)[0]

        except IndexError:
            # the container no longer exists
            return

        if not isinstance(container, DefinitionContainer):
            # skip containers that are not definitions
            return
        if container.getMetaDataEntry("type") == "extruder":
            # skip extruder definitions
            return

        speed_category = container.findDefinitions(key="speed")
        slowz_percentage = container.findDefinitions(key=list(self._settings_dict.keys())[0])
        slowz_height = container.findDefinitions(key=list(self._settings_dict.keys())[1])
        slowz_enable = container.findDefinitions(key=list(self._settings_dict.keys())[2])
        
        if speed_category and not slowz_percentage:            
            speed_category = speed_category[0]
            for setting_key, setting_dict in self._settings_dict.items():

                definition = SettingDefinition(setting_key, container, speed_category, self._i18n_catalog)
                definition.deserialize(setting_dict)

                # add the setting to the already existing platform adhesion setting definition
                speed_category._children.append(definition)
                container._definition_cache[setting_key] = definition
                container._updateRelations(definition)
    
    def _filterGcode(self, output_device):
        scene = self._application.getController().getScene()

        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return

        # get setting from Cura
        slowz_percentage = global_container_stack.getProperty("slowz_percentage", "value")
        slowz_height = global_container_stack.getProperty("slowz_height", "value")
        slowz_enable = global_container_stack.getProperty("slowz_enable", "value")
        
        if slowz_percentage <= 0:
            return

        if not slowz_enable:
            return        
        
        
        gcode_dict = getattr(scene, "gcode_dict", {})
        if not gcode_dict: # this also checks for an empty dict
            Logger.log("w", "Scene has no gcode to process")
            return

        dict_changed = False
        
        speed_value = 100 # start at 100% speed
        for plate_id in gcode_dict:
            gcode_list = gcode_dict[plate_id]
            if len(gcode_list) < 2:
                Logger.log("w", "G-Code %s does not contain any layers", plate_id)
                continue
            
            if ";SLOWZ\n" not in gcode_list[0]:
                layercount=0
                currentlayer=0
                currentz=0
                idl=0
                if ";LAYER_COUNT:" in gcode_list[1]:
                    if ";LAYER:0\n" in gcode_list[1]:
                        # layer 0 somehow got appended to the start gcode chunk
                        # left this in as it appears to be preventative for an error.
                        chunks = gcode_list[1].split(";LAYER:0\n")
                        gcode_list[1] = chunks[0]
                        gcode_list.insert(2, ";LAYER:0\n" + chunks[1])
                        
                    #finding layercount                    
                    flines = gcode_list[1].split("\n")
                    Logger.log("w", "gcode_list %d", len(gcode_list))
                    for (fline_nr, fline) in enumerate(flines):
                        if fline.startswith(";LAYER_COUNT:"):
                            Logger.log("w", "found LAYER_COUNT %s", fline[13:])
                            layercount=float(fline[13:])
                    Logger.log("w", "layercount %f", layercount)
                    #go through each layer
                    for i in range(len(gcode_list)):                    
                        lines = gcode_list[i].split("\n")
                        for (line_nr, line) in enumerate(lines):
                            if line.startswith(";LAYER:"):
                                currentlayer=float(line[7:])
                                Logger.log("w", "LAYER %s", line[7:])
                            
                                if line.startswith(";LAYER:0"):
                                    currentz=0
                                    idl=1    
                                    
                                if idl == 1 and currentz >= slowz_height:
                                    idl=2
                                    startlayer=currentlayer
                                    # Logger.log("w", "Z Height %f", currentz)                               
                                
                                if idl >= 2 :
                                    speed_value = 100 - int(float(slowz_percentage)*((currentlayer-startlayer)/(layercount-startlayer)))
                                    lines.insert(2,"M220 S" + str(speed_value))
                                    
                            if idl == 1 and is_z_line(line):
                                searchZ = re.search(r"Z(\d*\.?\d*)", line)
                                if searchZ:
                                    currentz=float(searchZ.group(1))
                                    # Logger.log('d', 'Current Z     : {:f}'.format(currentz))
                        
                        gcode_list[i] = "\n".join(lines)
                    gcode_list[0] += ";SLOWZ\n"
                    gcode_dict[plate_id] = gcode_list
                    dict_changed = True
            else:
                Logger.log("d", "G-Code %s has already been processed", plate_id)
                continue

        if dict_changed:
            setattr(scene, "gcode_dict", gcode_dict)
