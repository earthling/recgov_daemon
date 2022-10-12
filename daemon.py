"""
daemon.py

Main module for recgov daemon. Runs scrape_availabilty methods in a loop to detect new availability
for a list of campgrounds provided by the user or found in RIDB search.
"""

import argparse
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from signal import signal, SIGINT
from time import sleep
from typing import Set, Sequence

from availability import Availability, Criteria, parse_search_options
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


def compare_availability(availability: Availability,
                         campground_list: Set[Campground], criteria: Criteria) -> Sequence[Campground]:
    """
    Given a list of Campground objects, find out if any campgrounds' availability has changed
    since the last time we looked.
    :param availability: Used to coordinate searching
    :param campground_list: list of Campground objects we want to check against
    :param criteria: The availability search criteria
    :returns: list of campgrounds with availability matching search criteria
    """
    available = list()
    search_list = list(campground_list)
    for campground in search_list:
        logger.debug("Checking availability for %s", campground)
        sites_available = availability.search(campground, criteria)
        if sites_available:
            logger.info("%s is now available! Adding to email list and removing from active search list.", campground)
            available.append(campground)
            campground_list.remove(campground)
        else:
            logger.info("%s is not available, trying again in %s seconds", campground, RETRY_WAIT)

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
    message = email_start(available_campgrounds, to_email)
    message.set_content("")
    return message


def build_email_message(available_campgrounds, email):
    email_alert_msg = email_start(available_campgrounds, email)
    content = "The following campgrounds are now available!\n"
    for campground in available_campgrounds:
        content += f"\n{campground.name} {campground.url}"
    email_alert_msg.set_content(content)
    return email_alert_msg


def email_start(available_campgrounds, email):
    email_alert_msg = EmailMessage()
    email_alert_msg["From"] = GMAIL_USER
    email_alert_msg["To"] = email
    email_alert_msg["Subject"] = f"{len(available_campgrounds)} New Campgrounds Available"
    return email_alert_msg


def run():
    """
    Run the daemon after SIGINT has been captured and arguments have been parsed.
    """

    facilities = resolve_locations(args.where, args.radius)
    driver = Availability()
    criteria = parse_search_options(args.when, args.num_nights, args.num_sites)

    # check campground availability until stopped by user OR start_date has passed
    # OR no more campgrounds in search_list
    while True:
        available = compare_availability(driver, facilities, criteria)
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
    parser.add_argument("-s", "--when", type=str, action="append",
                        help="The date of any nights you want to camp. If `--num_nights` is given, the dates given"
                             " will be treated as the first night of your stay. Days of the week may also be given."
                             " You may also use 'max' to search for the maximum length stay at any campground. If"
                             " no dates are given and `--num_nights` is given, search for any campground with at"
                             " least this many consecutive nights available on any dates.")
    parser.add_argument("-n", "--num_nights", type=int,
                        help="Number of nights you want to camp (e.g. 2).")
    parser.add_argument("-e", "--email", type=str, required=True,
                        help="Email address at which you want to receive notifications (ex: first.last@example.com).")
    parser.add_argument("-t", "--text", type=str,
                        help="Phone number at which you want to receive text notifications (ex: 9998887777).")
    parser.add_argument("-c", "--carrier", choices=CARRIER_MAP.keys(),
                        help="Cell carrier for your phone number, required to send texts.")
    parser.add_argument("--num_sites", type=int, default=1,
                        help="Number of campsites you need at each campground; "
                             "this can be zero if you don't mind changing sites.")
    parser.add_argument("--where", type=str, action="append",
                        help="Can be 'City, State', 'Lat,Long', 'Campsite Name' or 'Campsite ID'")
    parser.add_argument("-r", "--radius", type=int,
                        help="Radius in miles of the area you want to search, centered on lat/lon (e.g. 25).")
    args = parser.parse_args()
    setup_logging()
    run()
