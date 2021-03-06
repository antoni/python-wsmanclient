#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import collections
import logging
import re

from wsmanclient import exceptions, utils, wsman
from wsmanclient.model import PSU
from wsmanclient.thinkserverclient import constants
from wsmanclient.thinkserverclient.resources import uris

LOG = logging.getLogger(__name__)

BOOT_MODE_IS_CURRENT = {
    '1': True,
    '2': False
}

BOOT_MODE_IS_NEXT = {
    '1': True,   # is next
    '2': False,  # is not next
    '3': True    # is next for single use (one time boot only)
}

LC_CONTROLLER_VERSION_12G = (2, 0, 0)

class PowerManagement(object):

    def __init__(self, client):
        """Creates PowerManagement object

        :param client: an instance of WSManClient
        """
        self.client = client

    def get_power_state(self):
        """Returns the current power state of the node

        :returns: power state of the node, one of 'POWER_ON', 'POWER_OFF' or
                  'REBOOT'
        :raises: WSManRequestFailure on request failures
        :raises: WSManInvalidResponse when receiving invalid response
        :raises: DRACOperationFailed on error reported back by the DRAC
                 interface
        """

        doc = self.client.enumerate(uris.CIM_ComputerSystem)

        enabled_state = doc.find(
            './/s:Body/wsen:EnumerateResponse/wsman:Items/wsinst:CIM_HostComputerSystem/wsinst:EnabledState', wsman.NS_MAP_COMPUTER_SYSTEM)
        return constants._get_enabled_state(enabled_state.text)

    def get_health_state(self):
        """Returns the current health state of the node

        :returns: health state of the node, one of 'UNKNOWN', 'OK', 'DEGRADED/WARNING' or 'ERROR'
        :raises: WSManRequestFailure on request failures
        :raises: WSManInvalidResponse when receiving invalid response
        :raises: DRACOperationFailed on error reported back by the DRAC
                 interface
        """

        doc = self.client.enumerate(uris.CIM_ComputerSystem)

        health_state = doc.find(
            './/s:Body/wsen:EnumerateResponse/wsman:Items/wsinst:CIM_HostComputerSystem/wsinst:HealthState', wsman.NS_MAP_COMPUTER_SYSTEM)
        return constants._get_health_state(health_state.text)

    def set_power_state(self, target_state):
        raise NotImplementedError

    def list_power_supply_units(self):
        """Returns the list of PSUs

        :returns: a list of PSU objects
        :raises: WSManRequestFailure on request failures
        :raises: WSManInvalidResponse when receiving invalid response
        :raises: DRACOperationFailed on error reported back by the DRAC
        """

        doc = self.client.enumerate(uris.CIM_PowerSupply)

        psus = doc.find('.//s:Body/wsen:EnumerateResponse/wsman:Items',
                wsman.NS_MAP)

        return [self._parse_psus(psu) for psu in psus]

    def _parse_psus(self, psu):
        return PSU(
            self._get_psu_attr(psu, 'DeviceID'),
            None
            #  constants._get_health_state(self._get_psu_attr(psu, 'HealthState'))
        )

    def _get_psu_attr(self, psu, attr_name):
        return utils.get_wsman_wsinst_resource_attr(psu, uris.CIM_PowerSupply,
                attr_name)

class BootManagement(object):

    def __init__(self, client):
        """Creates BootManagement object

        :param client: an instance of WSManClient
        """
        self.client = client

    def list_boot_modes(self):
        raise NotImplementedError

    def list_boot_devices(self):
        raise NotImplementedError
    
    def change_boot_device_order(self, boot_mode, boot_device_list):
        raise NotImplementedError


class BIOSAttribute(object):
    """Generic BIOS attribute class"""

    def __init__(self, name, current_value, pending_value, read_only):
        """Creates BIOSAttribute object

        :param name: name of the BIOS attribute
        :param current_value: current value of the BIOS attribute
        :param pending_value: pending value of the BIOS attribute, reflecting
                an unprocessed change (eg. config job not completed)
        :param read_only: indicates whether this BIOS attribute can be changed
        """
        self.name = name
        self.current_value = current_value
        self.pending_value = pending_value
        self.read_only = read_only

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    @classmethod
    def parse(cls, namespace, bios_attr_xml):
        """Parses XML and creates BIOSAttribute object"""

        name = utils.get_wsman_resource_attr(
            bios_attr_xml, namespace, 'AttributeName')
        current_value = utils.get_wsman_resource_attr(
            bios_attr_xml, namespace, 'CurrentValue', nullable=True)
        pending_value = utils.get_wsman_resource_attr(
            bios_attr_xml, namespace, 'PendingValue', nullable=True)
        read_only = utils.get_wsman_resource_attr(
            bios_attr_xml, namespace, 'IsReadOnly')

        return cls(name, current_value, pending_value, (read_only == 'true'))


class BIOSEnumerableAttribute(BIOSAttribute):
    """Enumerable BIOS attribute class"""

    #  namespace = uris.DCIM_BIOSEnumeration

    def __init__(self, name, current_value, pending_value, read_only,
                 possible_values):
        """Creates BIOSEnumerableAttribute object

        :param name: name of the BIOS attribute
        :param current_value: current value of the BIOS attribute
        :param pending_value: pending value of the BIOS attribute, reflecting
                an unprocessed change (eg. config job not completed)
        :param read_only: indicates whether this BIOS attribute can be changed
        :param possible_values: list containing the allowed values for the BIOS
                                attribute
        """
        super(BIOSEnumerableAttribute, self).__init__(name, current_value,
                                                      pending_value, read_only)
        self.possible_values = possible_values

    @classmethod
    def parse(cls, bios_attr_xml):
        raise NotImplementedError

    def validate(self, new_value):
        raise NotImplementedError


class BIOSStringAttribute(BIOSAttribute):
    """String BIOS attribute class"""

    #  namespace = uris.DCIM_BIOSString

    def __init__(self, name, current_value, pending_value, read_only,
                 min_length, max_length, pcre_regex):
        """Creates BIOSStringAttribute object

        :param name: name of the BIOS attribute
        :param current_value: current value of the BIOS attribute
        :param pending_value: pending value of the BIOS attribute, reflecting
                an unprocessed change (eg. config job not completed)
        :param read_only: indicates whether this BIOS attribute can be changed
        :param min_length: minimum length of the string
        :param max_length: maximum length of the string
        :param pcre_regex: is a PCRE compatible regular expression that the
                           string must match
        """
        super(BIOSStringAttribute, self).__init__(name, current_value,
                                                  pending_value, read_only)
        self.min_length = min_length
        self.max_length = max_length
        self.pcre_regex = pcre_regex

    @classmethod
    def parse(cls, bios_attr_xml):
        raise NotImplementedError

    def validate(self, new_value):
        raise NotImplementedError


class BIOSIntegerAttribute(BIOSAttribute):
    """Integer BIOS attribute class"""

    #  namespace = uris.DCIM_BIOSInteger

    def __init__(self, name, current_value, pending_value, read_only,
                 lower_bound, upper_bound):
        """Creates BIOSIntegerAttribute object

        :param name: name of the BIOS attribute
        :param current_value: current value of the BIOS attribute
        :param pending_value: pending value of the BIOS attribute, reflecting
                an unprocessed change (eg. config job not completed)
        :param read_only: indicates whether this BIOS attribute can be changed
        :param lower_bound: minimum value for the BIOS attribute
        :param upper_bound: maximum value for the BOIS attribute
        """
        super(BIOSIntegerAttribute, self).__init__(name, current_value,
                                                   pending_value, read_only)
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound

    @classmethod
    def parse(cls, bios_attr_xml):
        raise NotImplementedError

    def validate(self, new_value):
        raise NotImplementedError


class BIOSConfiguration(object):

    def __init__(self, client):
        """Creates BIOSConfiguration object

        :param client: an instance of WSManClient
        """
        self.client = client

    def list_bios_settings(self):
        raise NotImplementedError

    def set_bios_settings(self, new_settings):
        raise NotImplementedError
