import datetime
import os
import time
from enum import Enum
import logging

from src.sheet_manager import SheetReader
from src.solar_reader import SolarReader

log = logging.getLogger()


class State(Enum):
    SUNRISE_WAIT = 0
    SYS_ONLINE = 1
    SUNSET = 2


class SolarData:
    def __init__(self, sheet_reader: SheetReader, solar_reader: SolarReader):
        self.sheet_reader = sheet_reader
        self.solar_reader = solar_reader

        self.state = State.SUNRISE_WAIT

    def wait_on_sunrise(self):
        log.info("Waiting for sunrise...")
        while not self.solar_reader.is_online():
            # Check every 10 minutes to see if the solar system is online.
            time.sleep(600)

    @staticmethod
    def is_past_noon():
        dt = datetime.datetime.now()

        return dt.hour > 12

    def main_loop(self):
        """
        Main running loop.

        Every 10 minutes, the system will get the current status of the solar cells and
        log it to the google spreadsheet.
        If the number of microinverters drops to 0 (meaning sunset has happened), it exits out.
        """

        # The solar panels keep exiting early: my suspicions are that it falls out early for sunset due to initial
        # variances in voltages causing mi to drop below 0 after initializing.
        # Once we detect some activity, stay up until at least the afternoon

        log.info("Entering main loop")
        while self.solar_reader.is_online() or not self.is_past_noon():
            if not self.is_past_noon() and not self.solar_reader.is_online():
                log.error("Solar system shows as offline yet it is still morning.")
            try:
                cur_wh = self.solar_reader.get_wh_production()
                cur_mis = self.solar_reader.get_mi_online()
                cur_watts = self.solar_reader.get_current_watt_production()

                self.sheet_reader.update_row(cur_wh, cur_mis, cur_watts)
            except Exception:
                log.exception("An exception occurred in the main loop.")
            finally:
                time.sleep(600)

        log.info("Solar system is offline. Signing off for the night.")

    def run(self):
        """Start up the system."""
        log.info("Started, initializing...")

        # Check to see if the system is online. If it is, then we'll start right up.

        if self.solar_reader.is_online():
            log.info("Solar system online on startup.")
            self.main_loop()

        # otherwise, if 0 microinverters are online, it's either day or night.
        # if it's nighttime, we'll kill the program and let cron revive it tomorrow.
        # otherwise, we'll waitloop until the sun rises.

        else:

            if not self.is_past_noon():
                self.wait_on_sunrise()
                log.info("Microinverters have started, seems like sunrise. Main loop starting.")
                self.main_loop()
            else:
                log.warning("Program was started after sunset. Shutting down.")

        log.info("Run call ending, program terminating.")


if __name__ == '__main__':
    # TODO Convert some of these into command line args
    dirname = os.path.join(os.path.dirname(__file__), "config.json")
    sheet_reader = SheetReader()
    solar_reader = SolarReader("enphase", "192.168.1")

    solar_runner = SolarData(sheet_reader, solar_reader)
    solar_runner.run()
