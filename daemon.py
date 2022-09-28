"""
daemon.py

Main module for recgov daemon. Runs scrape_availabilty methods in a loop to detect new availability
for a list of campgrounds provided by the user or found in RIDB search.
"""

import argparse
import json
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from signal import signal, SIGINT
from time import sleep
from typing import Set, Sequence

from dateutil.parser import parse

from availability import Availability
from campground import Campground
from locations import resolve_locations
from utils import exit_gracefully, setup_logging

# import asyncio
# import aiosmtplib

logger = logging.getLogger(__name__)

# set in ~/.virtualenvs/recgov_daemon/bin/postactivate
GMAIL_USER = os.environ.get("gmail_user")
GMAIL_APP_PASSWORD = os.environ.get("gmail_app_password")
CARRIER_MAP = {
    "verizon": "vtext.com",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "at&t": "txt.att.net",
    "boost": "smsmyboostmobile.com",
    "cricket": "sms.cricketwireless.net",
    "uscellular": "email.uscc.net",
}
RETRY_WAIT = 300


def email_notification(message: EmailMessage) -> bool:
    """
    We send both texts and emails via this base function. For now, we're hardcoding GMAIL
    as our email service because that's what we use in development. Another user/dev should
    be able to easily change this configuration.

    Retry sending email 5 times before returning with failure if we can't send an email.

    :param message: EmailMessage object to enable using send_message rather than sendmail.
    :returns: True if notification sent correctly, False otherwise.

    TODO: make notifications asynchronous
    Note that because SMTP is a sequential protocol, `aiosmtplib.send` must be
    executed in sequence as well, which means that doing this asyncronously is essentially
    equivalent to doing it normally. To get the benefit, we need to create a new connection
    object entirely for different emails (in this case we create 2 of them).
    Ref: https://aiosmtplib.readthedocs.io/en/v1.0.6/overview.html#parallel-execution
    """
    logger.info("Sending alert for available campgrounds to %s.", message["To"])
    smtp_server = "smtp.gmail.com"  # hardcode using gmail for now
    port = 587  # ensure starttls
    num_retries = 5

    for attempts in range(num_retries):
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_server, port=port, timeout=5) as server:
                server.starttls(context=context)
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.send_message(message)
            break
        except (smtplib.SMTPRecipientsRefused,
                smtplib.SMTPHeloError,
                smtplib.SMTPSenderRefused,
                smtplib.SMTPDataError,
                smtplib.SMTPNotSupportedError,
                smtplib.SMTPAuthenticationError,
                smtplib.SMTPException) as exp:
            logger.error("FAILURE: could not send email due to the following exception; retrying %d times:\n%s",
                         num_retries - attempts, exp)
    else:  # will run if we didn't break out of the loop, so only failures
        logger.error("Failed to send alert %d times; exiting with failure", num_retries)
        return False
    logger.info("Sent alert for available campgrounds to %s.", message["To"])
    return True


def compare_availability(availability: Availability, campground_list: Set[Campground],
                         start_date, num_days: int, num_sites: int = 1) -> Sequence[Campground]:
    """
    Given a list of Campground objects, find out if any campgrounds' availability has changed
    since the last time we looked.

    :param campground_list: list of Campground objects we want to check against
    :returns: N/A
    """
    available = list()
    search_list = list(campground_list)
    for campground in search_list:
        logger.debug("Checking availability for %s", campground)
        sites_available = availability.search(campground, start_date, num_days, num_sites)
        if sites_available:
            logger.info("%s is now available! Adding to email list and removing from active search list.", campground)
            available.append(campground)
            campground_list.remove(campground)
        else:
            logger.info("%s is not available, trying again in %s seconds", campground, RETRY_WAIT)

        # if campground parsing has errored more than 5 times in a row
        # remove it from the CampgroundList so we can stop checking it and failing
        if campground.error_count > 5:
            err_msg = f"Campground errored more than 5 times in a row, removing it from list:\n{campground}"
            logger.error(err_msg)
            campground_list.remove(campground)

    return available


def send_alerts(available_campgrounds: Sequence[Campground], email: str, text_number: str, carrier: str) -> bool:
    """
    Builds and sends 2 emails:
      - one for an email alert sent to a convetional email address
      - one for a text alert sent via carrier email/text gateway

    :param available_campgrounds: list of newly available sites to send notifications for
    :returns: True if both email and text notifications succeed, False otherwise.
    """
    # build email message
    email_alert_msg = build_email_message(available_campgrounds, email)

    # build text message
    text_alert_msg = build_text_message(available_campgrounds, carrier, text_number)

    # send alerts; retry 5 times if doesn't succeed; exit gracefully if fails repeatedly
    return email_notification(email_alert_msg) and email_notification(text_alert_msg)


def build_text_message(available_campgrounds, carrier, text_number):
    carrier_domain = CARRIER_MAP[carrier]
    to_email = f"{text_number}@{carrier_domain}"
    return build_email_message(available_campgrounds, to_email)


def build_email_message(available_campgrounds, email):
    email_alert_msg = EmailMessage()
    email_alert_msg["From"] = GMAIL_USER
    email_alert_msg["To"] = email
    email_alert_msg["Subject"] = f"{len(available_campgrounds)} New Campgrounds Available"
    content = "The following campgrounds are now available!\n"
    for campground in available_campgrounds:
        content += f"\n{campground.name} {campground.url}"
    email_alert_msg.set_content(content)
    return email_alert_msg


def parse_start_day(arg: str) -> datetime:
    """
    Parse user input start date as Month/Day/Year (e.g. 05/19/2021).

    :param arg: date represented as a string
    :returns: datetime object representing the user-provided day
    """
    return parse(arg).date()


def validate_carrier(arg: str) -> str:
    """
    Carrier has to be something that we can map back to a gateway, so
    check that the entered text is a key in the carrier map dict. Accept
    mixture of uppercase/lowercase just to be nice.

    :param arg: the user-entered carrier name
    :returns: lowercase str version of the entered carrier if present in carrier map dict
    """
    lowercase_arg = arg.lower()
    if lowercase_arg not in CARRIER_MAP:
        logger.error("KeyError: carrier '%s' not found in CARRIER_MAP dict:\n%s",
                     lowercase_arg, json.dumps(CARRIER_MAP))
        sys.exit(1)
    return lowercase_arg


def validate_num_sites(arg: str) -> int:
    """
    Number of campsites has to be an integer >= 1 for sanity's sake.

    :param arg: user-entered number of sites
    :returns: integer >= 1
    """
    arg = int(arg)
    if arg < 1:
        logger.error("User input for number of campsites (%d) too small (must be > 1)", arg)
        sys.exit(1)
    return arg


def run():
    """
    Run the daemon after SIGINT has been captured and arguments have been parsed.
    """

    facilities = resolve_locations(args.where)
    driver = Availability()

    # check campground availability until stopped by user OR start_date has passed
    # OR no more campgrounds in search_list
    while True:
        start_date = max(args.start_date, datetime.now().date())
        available = compare_availability(driver, facilities, start_date, args.num_nights, args.num_sites)
        if len(available) > 0:
            if not send_alerts(available, args.email, args.text, args.carrier):
                logging.error("Could not send alerts.")
                return
        if len(facilities) == 0:
            logger.info(("All campgrounds to be searched have either been found or ",
                         "encountered multiple errors, ending process..."))
            return
        sleep(RETRY_WAIT)  # sleep for RETRY_WAIT time before checking search_list again


if __name__ == "__main__":
    signal(SIGINT, exit_gracefully)  # add custom handler for SIGINT/CTRL-C
    ARG_DESC = """Daemon to check recreation.gov and RIDB for new campground availability and send notification email
        when new availability found."""
    parser = argparse.ArgumentParser(description=ARG_DESC)
    parser.add_argument("-s", "--start_date", type=parse_start_day, required=True,
                        help="First day you want to reserve a site, represented as Month/Day/Year (e.g. 05/19/2021).")
    parser.add_argument("-n", "--num_nights", type=int, required=True,
                        help="Number of nights you want to camp (e.g. 2).")
    parser.add_argument("-e", "--email", type=str, required=True,
                        help="Email address at which you want to receive notifications (ex: first.last@example.com).")
    parser.add_argument("-t", "--text", type=str,
                        help="Phone number at which you want to receive text notifications (ex: 9998887777).")
    parser.add_argument("-c", "--carrier", type=validate_carrier, choices=CARRIER_MAP.keys(),
                        help="Cell carrier for your phone number, required to send texts.")
    parser.add_argument("--num_sites", type=validate_num_sites,
                        help="Number of campsites you need at each campground; defaults to 1, validated to be >0.")
    parser.add_argument("--where", type=str, action="append",
                        help="Can be 'City, State', 'Lat,Long', 'Campsite Name' or 'Campsite ID'")
    parser.add_argument("-r", "--radius", type=int,
                        help="Radius in miles of the area you want to search, centered on lat/lon (e.g. 25).")
    args = parser.parse_args()
    setup_logging()
    run()
