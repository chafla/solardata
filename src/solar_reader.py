import re
import logging
import requests
from lxml import html

log = logging.getLogger()


number_pattern = re.compile(r"([\d.]+)")


class SolarReader:
    """
    Handles the direct net interface with the solar panels.
    """

    def __init__(self, tag: str, base_ip_range: str, static_ip: str = None):
        """
        Create the base interface.
        :param tag: Tag to use when trying to find the solar web interface.
        :param base_ip_range: IP range of the network to search. The IP
        :param static_ip: Optional static IP address. If a value is specified, then we won't attempt to search for a
        valid IP address if we can't access it.
        """

        # On init, we want to verify that we can access the solar panel.
        # Might as well duck out while we still can.

        self._tag = tag
        self._base_ip_range = base_ip_range

        self._using_static_ip = bool(static_ip)
        if self._using_static_ip:
            self._ip_address = static_ip
            if not self.solar_panels_accessible():
                raise RuntimeError("Static IP was specified but connection could not be made.")
        else:
            log.info("Searching for IP address.")
            self._ip_address = self.get_ip_address()

        if not self._ip_address:
            raise RuntimeError("Connection could not be established to solar device.")
        else:
            log.info("Found solar device at IP address {}".format(self._ip_address))

    def is_online(self) -> bool:
        """Returns whether the system should be marked as offline due to not enough microinverters being online"""
        return self.get_mi_online() > 0

    def get_ip_address(self) -> str:
        """
        Get the IP address of the solar panel.

        Performs a quick scan through IP addresses on the network, and
        runs a quick regex pattern match on the HTML to see if the page
        contains our input tag. If it does, return the IP address found.

        :return: IP address, or None if no IP can be found.
        """

        if self._using_static_ip:
            return self._ip_address

        for i in range(0, 256):
            ip = "{}.{}".format(self._base_ip_range, i)
            try:
                response = requests.get('http://%s' % ip, timeout=2)
                if re.search(self._tag, response.text):
                    return ip
            except (requests.ConnectionError, requests.Timeout):
                continue

    def solar_panels_accessible(self) -> bool:
        """
        Get whether or not the solar panels are accessible at their IP address
        """

        log.info("Determining connection to solar system...")
        try:
            response = self.get_response("/")
            log.info("Connected successfully")
            return response.status_code == 200
        except requests.ConnectionError:
            log.exception(
                "Error: Can't connect to the solar array. Check the POE connection, or the status on the box.")
            raise

    def get_response(self, path) -> requests.Response:
        """
        Get a given HTTP response from a
        :param ip: ip address that we believe it's at
        :param path: Should be the full path including a leading slash if necessary
        :return:
        """

        try:
            response = requests.get("http://{}{}".format(self._ip_address, path))
        except requests.ConnectionError as e:
            if self._using_static_ip:
                raise e
            new_ip = self.get_ip_address()
            if new_ip is not None:
                self._ip_address = new_ip
                log.info("IP address updated to {}.".format(new_ip))
                response = requests.get("http://{}{}".format(new_ip, path))
            else:
                raise RuntimeError("A seemingly valid IP address failed.")

        return response

    def get_wh_production(self) -> int:
        """
        Get the total energy generated today in watt-hours.
        """
        page = self.get_response("/production")  # Pull the webpage
        tree = html.fromstring(page.text)
        data = tree.xpath("/html/body/div[1]/table/tr[3]/td[2]/text()")  # Grab the value

        match = number_pattern.findall(data[0])
        try:
            data_float = float(match[0])
        except ValueError:
            log.exception("Couldn't convert to float")
            return 0

        if "kW" in data[0]:
            data_float *= 1000

        energy_wh = int(data_float)  # Convert it to the base unit, watt hours, to make math easier
        return energy_wh

    def get_current_watt_production(self) -> float:
        """
        Get the current amount of watts being generated by the solar panels.
        """
        page = self.get_response("/production")
        # page = requests.get("http://%s/production" % ip_address)
        tree = html.fromstring(page.text)
        data = tree.xpath("/html/body/div[1]/table/tr[2]/td[2]/text()")
        match = number_pattern.findall(data[0])
        try:
            data_float = float(match[0])
        except ValueError:
            log.exception("Couldn't convert to float")
            return 0
        # cur_kw = float(data[0].strip().rstrip(" kW"))

        if "kW" in data[0]:
            data_float *= 1000  # Convert it to watts
        return data_float

    def get_mi_online(self):
        """
        Get the current number of microinverters online.

        Microinverters are small power inverters that route power from the solar cells
        and keep track of their power generation.
        They are automatically turned on and off depending on the sunlight reaching their associated
        panels, and therefore make for a good measure of the health of the system.
        """
        log.info("Determining current solar cell status...")
        page = self.get_response("/home")
        tree = html.fromstring(page.text)
        data = tree.xpath("/html/body/table/tr/td[2]/table/tr[5]/td[2]/text()")
        mi_online = int(data[0])
        # Note: I had to remove tbody from xpath Chrome gave me, and add '/text()' after it.
        log.debug("%s out of 24 microinverters online" % mi_online)
        return mi_online
