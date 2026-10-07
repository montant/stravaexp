from datetime import datetime, timedelta
import json
import logging
import os
import time
from urllib.parse import urlsplit
from stravalib.util import limiter
from stravalib import exc



LAST_PARSED_FILE = os.path.join(os.path.dirname(__file__), "last_parsed_date.txt")
GEAR_ID_2_NAME = {}


DEFAULT_FIRST_DATE = "2025-12-12"


def _write_last_parsed_date(last_date):
    temp_path = LAST_PARSED_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as temporary:
        temporary.write(last_date)
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temp_path, LAST_PARSED_FILE)


def _load_last_parsed_date():
    if not os.path.exists(LAST_PARSED_FILE):
        return DEFAULT_FIRST_DATE

    try:
        with open(LAST_PARSED_FILE, "r", encoding="utf-8") as file_handle:
            raw = file_handle.read().strip()
        if not raw:
            return DEFAULT_FIRST_DATE

        datetime.fromisoformat(raw)
        return raw
    except (ValueError, OSError):
        return DEFAULT_FIRST_DATE


def _sleep_for_rate_limit(response, method, attempt=1):
    if response is None:
        wait = min(300, 5 * 2 ** (attempt - 1))
        logging.warning("Rate limit response missing headers; sleeping %s seconds", wait)
        time.sleep(wait)
        return

    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            wait = int(float(retry_after))
        except (TypeError, ValueError):
            wait = 60
        logging.warning("Rate limit Retry-After header; sleeping %s seconds", wait)
        time.sleep(wait + 1)
        return

    rates = limiter.get_rates_from_response_headers(headers, method)
    if rates:
        if rates.short_usage >= rates.short_limit:
            wait = limiter.get_seconds_until_next_quarter()
            logging.warning("Short-term rate limit exceeded; sleeping %s seconds", wait)
            time.sleep(wait + 1)
            return
        if rates.long_usage >= rates.long_limit:
            wait = limiter.get_seconds_until_next_day()
            logging.warning("Long-term rate limit exceeded; sleeping %s seconds", wait)
            time.sleep(wait + 1)
            return

    wait = min(300, 5 * 2 ** (attempt - 1))
    logging.warning("Rate limit hit with unknown headers; sleeping %s seconds", wait)
    time.sleep(wait)


def _retry_api_call(func, method, *args, **kwargs):
    max_attempts = 8
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except (exc.RateLimitExceeded, exc.Fault) as error:
            response = getattr(error, "response", None)
            status_code = None
            if response is not None:
                status_code = getattr(response, "status_code", None)
            if isinstance(error, exc.RateLimitExceeded) or status_code in (429, 503):
                last_error = error
                _sleep_for_rate_limit(response, method, attempt)
                continue
            raise
    raise last_error


def _update_activity_with_logging(client, activity_id, **fields):
    def log_response(response, *args, **kwargs):
        request = response.request
        if (
            request.method != "PUT"
            or urlsplit(request.url).path
            != f"/api/v3/activities/{activity_id}"
        ):
            return
        try:
            sent = json.loads(request.body)
            received = response.json()
        except (TypeError, ValueError):
            logging.warning(
                "Activity PUT id=%s HTTP=%s: non-JSON request or response",
                activity_id, response.status_code
            )
            return
        if not isinstance(sent, dict) or not isinstance(received, dict):
            logging.warning(
                "Activity PUT id=%s HTTP=%s: unexpected JSON structure",
                activity_id, response.status_code
            )
            return
        safe_fields = ("name", "commute", "sport_type", "type")
        sent_fields = {
            key: sent[key] for key in safe_fields if key in sent
        }
        received_fields = {
            key: received[key]
            for key in ("id", *safe_fields) if key in received
        }
        logging.info(
            "Activity PUT id=%s sent=%r HTTP=%s returned=%r",
            activity_id, sent_fields, response.status_code, received_fields
        )

    response_hooks = client.protocol.rsession.hooks["response"]
    response_hooks.append(log_response)
    try:
        return client.update_activity(activity_id=activity_id, **fields)
    finally:
        response_hooks.remove(log_response)


def get_gear_name(client, gear_id):
    gear_name = GEAR_ID_2_NAME.get(gear_id)
    if not gear_name:
        try:
            gear_name = _retry_api_call(client.get_gear, "GET", gear_id).name
        except exc.Fault:
            gear_name = None
        GEAR_ID_2_NAME[gear_id] = gear_name
    return gear_name

def process_activities(client):

    first_date = _load_last_parsed_date()
    last_parsed_date = first_date
    commuting_threshold = timedelta(minutes=45)
    activities = client.get_activities(after=first_date)
    activity_iterator = iter(activities)
    activity_retry_attempt = 0
    nb_rides_edited = 0
    nb_workout_edited = 0
    nb_activity = 0
    ride_kms = 0
    
    max_heartrate = 0
    activity_with_max_heartrate = None
    
    while True:
        try:
            activity = next(activity_iterator)
            activity_retry_attempt = 0
        except StopIteration:
            break
        except (exc.RateLimitExceeded, exc.Fault) as error:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None) if response is not None else None
            if isinstance(error, exc.RateLimitExceeded) or status_code == 429:
                activity_retry_attempt += 1
                if activity_retry_attempt > 8:
                    raise
                _sleep_for_rate_limit(response, "GET", activity_retry_attempt)
                continue
            raise

        if activity.max_heartrate and activity.max_heartrate > 175:
            if activity.type in ("EBikeRide", "Yoga", "Workout"):
                continue
            if activity.max_heartrate > 200:
                print("Skipping suspiciously high heartrate of {} in activity {} / {} / {}".format(activity.max_heartrate, activity.type, activity.name, activity.start_date))
                continue
            if activity.max_heartrate > max_heartrate:
                max_heartrate = activity.max_heartrate
                activity_with_max_heartrate = activity
                print("New max heartrate {} in activity {} / {} / {}".format(max_heartrate, activity.type, activity.name, activity.start_date))
            else:
                print("High heartrate {} in activity {} / {} / {}".format(activity.max_heartrate, activity.type, activity.name, activity.start_date))
        time.sleep(1.5)  # Avoid hitting rate limits
        activity_date = activity.start_date.isoformat()
        if activity_date <= last_parsed_date:
            print("     Skipping already covered activity {} / {} / {}".format(activity.type, activity.name, activity.start_date))
            continue
        last_parsed_date = max(last_parsed_date, activity_date)
        _write_last_parsed_date(last_parsed_date)
        nb_activity += 1
        try:
            print(activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
        except:
            print(activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
            
        ebike_update_accepted = False
        is_custom_workout = activity.type == "Workout" and activity.average_speed > 0.0
        if (activity.type.root == 'Ride' or is_custom_workout) and timedelta(seconds=activity.moving_time) < commuting_threshold:
            activity_updates = {}
            if not activity.commute:
                print("     One short ride set to commute")
                activity_updates["commute"] = True
            if activity.name != "Vélotaf":
                print("    One short ride set to Vélotaf")
                activity_updates["name"] = "Vélotaf"
            if activity.gear_id:
                bike_name = get_gear_name(client, activity.gear_id)
            is_ebike = not activity.gear_id or bike_name == 'Moustache'
            if is_ebike:
                print(f"     Converting activity {activity.id} to EBikeRide")
                activity_updates["sport_type"] = "EBikeRide"
            else:
                print(f"    commuting activity not set to EBike as bike is: {bike_name}")
            if activity_updates:
                activity = _retry_api_call(
                    _update_activity_with_logging, "PUT", client,
                    activity_id=activity.id,
                    **activity_updates
                )
            if is_ebike:
                # A PUT returned Workout while Strava later showed E-Bike Ride.
                # The timing/cause is unclear. Track the accepted update
                # separately so old response fields cannot trigger Yoga.
                ebike_update_accepted = True
                if (
                    activity.sport_type is None
                    or activity.sport_type.root != "EBikeRide"
                ):
                    logging.warning(
                        "Activity %s: EBikeRide PUT accepted, but response "
                        "sport_type=%r; persistence not verified by script",
                        activity.id, activity.sport_type
                    )
                print(
                    f"     Activity {activity.id}: EBikeRide update accepted"
                )
            nb_rides_edited += 1
            
        if activity.type == "Workout" and not ebike_update_accepted:
            if not activity.private:
                print("     One public workout converted to Yoga")
                _retry_api_call(client.update_activity, "PUT", activity_id=activity.id, name="Yoga", sport_type="Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            else:
                _retry_api_call(client.update_activity, "PUT", activity_id=activity.id, name="Yoga", sport_type="Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            
        if activity.type == "Yoga":
            if not activity.private:
                print("     One public yoga workout updated")
                updated_activity = _retry_api_call(client.update_activity, "PUT", activity_id=activity.id, name="Yoga")
                nb_workout_edited += 1
                
        if activity.type == "EBikeRide" and not ebike_update_accepted:
            if not activity.private:
                print("     One public e-bike ride left unchanged")
                nb_rides_edited += 1
                
        if activity.type == 'Ride' and not ebike_update_accepted:
            if activity.start_date_local.year < 2021:
                continue
            this_ride_kms = int(activity.distance / 1000.0)
            if this_ride_kms > 30:
                bike_name = get_gear_name(client, activity.gear_id)
                if bike_name == "Moustache":
                    logging.error("Moustache e-bike is associated to a ride > 30 kms")
            ride_kms = ride_kms + this_ride_kms

    print("#rides > {fd} kms: {rk}".format(fd=first_date, rk=ride_kms))
    print("#rides edited: ", nb_rides_edited)
    print( "#workout edited: ", nb_workout_edited)
    print("#activities: ", nb_activity)
    if activity_with_max_heartrate:
        print(
            "activity with max heart rate: ",
            activity_with_max_heartrate.type,
            activity_with_max_heartrate.name,
            activity_with_max_heartrate.start_date)
        print("Max heart rate: ", max_heartrate)

    return {
        "nb_activity": nb_activity,
        "nb_workout_edited": nb_workout_edited,
        "nb_ride_edited": nb_rides_edited
    }