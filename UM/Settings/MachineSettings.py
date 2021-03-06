# Copyright (c) 2015 Ultimaker B.V.
# Uranium is released under the terms of the AGPLv3 or higher.

import traceback
import sys
import json
import configparser
import os.path
import collections

from UM.Settings.SettingsCategory import SettingsCategory
from UM.Settings.Setting import Setting
from UM.Settings.Profile import Profile
from UM.Settings.Validators.ResultCodes import ResultCodes
from UM.Settings import SettingsError
from UM.Signal import Signal, SignalEmitter
from PyQt5.QtCore import QCoreApplication
from UM.Logger import Logger
from UM.Resources import Resources
from UM.i18n import i18nCatalog

class MachineSettings(SignalEmitter):
    MachineDefinitionVersion = 1
    MachineInstanceVersion = 1

    def __init__(self):
        super().__init__()
        self._categories = []
        self._platform_mesh = None
        self._platform_texture = None
        self._name = "Unknown Machine"
        self._type_name = "Unknown"
        self._type_id = "unknown"
        self._type_version = "unknown"
        self._json_file = ""
        self._icon = "unknown.png",
        self._machine_settings = []   ## Settings that don't have a category are 'fixed' (eg; they can not be changed by the user, unless they change the json)
        self._i18n_catalog = None
        self._active_profile = None
        
    def _onSettingChanged(self, setting):
        if self._active_profile: # Should be a profile if this function is connected to settingChanged
            self._active_profile.setSettingValue(setting.getKey(),setting.getValue())

    def getActiveProfile(self):
        return self._active_profile

    def setActiveProfile(self, profile):
        if self._active_profile:
            self.settingChanged.disconnect(self._onSettingChanged)

        if profile:
            changed_settings = profile.getChangedSettings()
            # Reset settings to default
            for setting in self.getAllSettings():
                setting.setValue(setting.getDefaultValue())
            
            # Set all setting values to saved values
            for setting_key in changed_settings:
                setting = self.getSetting(setting_key)
                if setting:
                    setting.setValue(changed_settings[setting_key])
            self.settingChanged.connect(self._onSettingChanged)
        self._active_profile = profile

    ##  Load settings from JSON file. Used to load tree structure & default values etc from file.
    #   \param file_name String
    def loadSettingsFromFile(self, file_name):
        with open(file_name, "rt", -1, "utf-8") as f:
            data = json.load(f, object_pairs_hook=collections.OrderedDict)

        if "id" not in data or "name" not in data:
            raise SettingsError.InvalidFileError(file_name)

        if "version" not in data or data["version"] != self.MachineDefinitionVersion:
            raise SettingsError.InvalidVersionError(file_name)

        self._i18n_catalog = i18nCatalog(os.path.basename(file_name))

        self._json_file = file_name

        self._type_id = data["id"]
        self._type_name = data["name"]

        if "platform" in data:
            self._platform_mesh = data["platform"]

        if "platform_texture" in data:
            self._platform_texture = data["platform_texture"]

        if "version" in data:
            self._type_version = str(data["version"])

        if "icon" in data:
            self._icon = data["icon"]

        if "inherits" in data:
            inherits_from = MachineSettings()
            inherits_from.loadSettingsFromFile(os.path.dirname(file_name) + "/" + data["inherits"])
            self._machine_settings = inherits_from._machine_settings
            self._categories = inherits_from._categories

        if "machine_settings" in data:
            for key, value in data["machine_settings"].items():
                setting = self.getSettingByKey(key)
                if not setting:
                    setting = Setting(key, self._i18n_catalog)
                    self.addSetting(setting)
                setting.fillByDict(value)

        if "categories" in data:
            for key, value in data["categories"].items():
                category = self.getSettingsCategory(key)
                if not category:
                    category = SettingsCategory(key, self._i18n_catalog, self)
                    self.addSettingsCategory(category)
                category.fillByDict(value)

        if "overrides" in data:
            for key, value in data["overrides"].items():
                setting = self.getSettingByKey(key)
                if not setting:
                    continue

                setting.fillByDict(value)

        for setting in self.getAllSettings():
            setting.valueChanged.connect(self.settingChanged)

        self.settingsLoaded.emit() #Emit signal that all settings are loaded (some setting stuff can only be done when all settings are loaded (eg; the conditional stuff)
    settingsLoaded = Signal()

    def loadFromFile(self, path):
        config = configparser.ConfigParser()
        config.read(path)

        if not config.has_section("General"):
            raise SettingsError.InvalidFileError(path)

        if not config.has_option("General", "version") or int(config.get("General", "version")) != self.MachineInstanceVersion:
            raise SettingsError.InvalidVersionError(path)

        if not config.has_option("General", "name") or not config.has_option("General", "json_file"):
            raise SettingsError.InvalidFileError(path)

        try:
            self.loadSettingsFromFile(Resources.getPath(Resources.MachineDefinitions, config["General"]["json_file"]))
        except FileNotFoundError:
            raise SettingsError.InvalidFileError(path)

        self._name = config.get("General", "name", fallback = "Unknown Machine")

    def saveToFile(self, path):
        config = configparser.ConfigParser()

        config.add_section("General")
        config["General"]["name"] = self._name
        config["General"]["json_file"] = os.path.basename(self._json_file)
        config["General"]["version"] = str(self.MachineInstanceVersion)

        with open(path, "wt") as f:
            config.write(f)

    def getTypeName(self):
        return self._type_name
    
    def getTypeID(self):
        return self._type_id
    
    ##  Add a category of settings
    def addSettingsCategory(self, category):
        self._categories.append(category)

    ##  Get setting category by key
    #   \param key Category key to get.
    #   \return category or None if key was not found.
    def getSettingsCategory(self, key):
        for category in self._categories:
            if category.getKey() == key:
                return category
        return None

    ##  Get all categories.
    #   \returns list of categories
    def getAllCategories(self):
        return self._categories

    ##  Get all settings of this machine
    #   \param kwargs Keyword arguments.
    #                 Possible values are:
    #                 * include_machine: boolean, True if machine settings should be included. Default False.
    #                 * visible_only: boolean, True if only visible settings should be included. Default False.
    #   \return list of settings
    def getAllSettings(self, **kwargs):
        all_settings = []
        if kwargs.get("include_machine", False):
            all_settings.extend(self._machine_settings)

        for category in self._categories:
            all_settings.extend(category.getAllSettings())

        if kwargs.get("visible_only"):
            all_settings = filter(lambda s: s.isVisible(), all_settings)

        return all_settings

    ##  Get machine settings of this machine (category less settings).
    #   \return list of settings
    def getMachineSettings(self):
        return self._machine_settings

    ##  Get setting by key.
    #   \param key Key to select setting by (string)
    #   \return Setting or none if no setting was found.
    def getSettingByKey(self, key):
        for category in self._categories:
            setting = category.getSettingByKey(key)
            if setting is not None:
                return setting
        for setting in self._machine_settings:
            setting = setting.getSettingByKey(key)
            if setting is not None:
                return setting
        return None #No setting found

    ##  Add (machine) setting to machine.
    def addSetting(self, setting):
        self._machine_settings.append(setting)
        setting.valueChanged.connect(self.settingChanged)

    ##  Set the value of a setting by key.
    #   \param key Key of setting to change.
    #   \param value value to set.
    def setSettingValueByKey(self, key, value):
        setting = self.getSettingByKey(key)
        if setting is not None:
            setting.setValue(value)

    ##  Get the value of setting by key.
    #   \param key Key of the setting to get value from
    #   \return value (or none)
    def getSettingValueByKey(self, key):
        setting = self.getSettingByKey(key)
        if setting is not None:
            return setting.getValue()
        return None

    settingChanged = Signal()

    ##  Get the machine mesh (in most cases platform)
    #   Todo: Might need to rename this to get machine mesh?
    def getPlatformMesh(self):
        return self._platform_mesh

    def getPlatformTexture(self):
        return self._platform_texture

    ##  Return the machine name.
    def getName(self):
        return self._name

    ##  Set the machine name
    #
    #   \param name The name of the machine.
    def setName(self, name):
        self._name = name

    ##  Returns the machine"s icon.
    def getIcon(self):
        return self._icon

    ##  Return whether there is any setting that is in an "Error" state.
    def hasErrorValue(self):
        settings = self.getAllSettings()
        for setting in settings:
            result = setting.validate()
            if result == ResultCodes.max_value_error or result == ResultCodes.min_value_error:
                return True

        return False

    ##  Return whether there is any setting that is in a "Warning" state.
    def hasWarningValue(self):
        settings = self.getAllSettings()
        for setting in settings:
            result = setting.validate()
            if result == ResultCodes.max_value_warning or result == ResultCodes.min_value_warning:
                return True

        return False
