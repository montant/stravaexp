from datetime import timedelta
import json
import logging
import os
import time
from stravalib.util import limiter
from stravalib import exc



ACTIVITIES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "activities.json")
GEAR_ID_2_NAME = {}


def _write_activities_checkpoint(activity_ids):
    temp_path = ACTIVITIES_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as temporary:
        for activity_id in activity_ids:
            temporary.write(f"{activity_id}\n")
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temp_path, ACTIVITIES_FILE)


def _load_activities_checkpoint():
    if not os.path.exists(ACTIVITIES_FILE):
        return {}

    try:
        with open(ACTIVITIES_FILE, "r", encoding="utf-8") as file_handle:
            content = file_handle.read()
        if not content.strip():
            return {}

        if content.lstrip().startswith("{"):
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                activity_ids = list(parsed.keys())
                _write_activities_checkpoint(activity_ids)
                return {activity_id: True for activity_id in activity_ids}

        return {line.strip(): True for line in content.splitlines() if line.strip()}
    except (json.JSONDecodeError, OSError):
        try:
            with open(ACTIVITIES_FILE, "r", encoding="utf-8") as file_handle:
                return {line.strip(): True for line in file_handle if line.strip()}
        except OSError:
            return {}


def _append_activity_checkpoint(activity_id, file_handle):
    file_handle.write(f"{activity_id}\n")
    file_handle.flush()
    os.fsync(file_handle.fileno())


def get_gear_name(client, gear_id):
    gear_name = GEAR_ID_2_NAME.get(gear_id)
    if not gear_name:
        try:
            gear_name = client.get_gear(gear_id).name
        except exc.Fault:
            gear_name = None
        GEAR_ID_2_NAME[gear_id] = gear_name
    return gear_name

def process_activities(client):

    already_parsed_activities = _load_activities_checkpoint()
    checkpoint_handle = open(ACTIVITIES_FILE, "a", encoding="utf-8")

    first_date = "2024-06-01"
    first_date = "2020-01-01"
    commuting_threshold = timedelta(minutes=45)
    activities = client.get_activities(after=first_date)
    nb_rides_edited = 0
    nb_workout_edited = 0
    nb_activity = 0
    ride_kms = 0
    
    max_heartrate = 0
    activity_with_max_heartrate = None
    
    for activity in activities:
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
        if str(activity.id) in already_parsed_activities.keys():
            print("     Skipping already parsed activity {} / {} / {}".format(activity.type, activity.name, activity.start_date))
            continue
        time.sleep(1.5)  # Avoid hitting rate limits
        activity_id = str(activity.id)
        already_parsed_activities[activity_id] = True
        _append_activity_checkpoint(activity_id, checkpoint_handle)
        nb_activity += 1
        try:
            print(activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
        except:
            print(activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
            

        if (activity.type.root == 'Ride') and timedelta(seconds=activity.elapsed_time) < commuting_threshold:
            if not activity.commute:
                print("     One short ride set to commute")
                client.update_activity(activity_id=activity.id, commute=True)
            if activity.name != "Vélotaf":
                print("    One short ride set to Vélotaf")
                client.update_activity(activity_id=activity.id, name="Vélotaf")
            assert activity.gear_id
            bike_name = get_gear_name(client, activity.gear_id)
            is_ebike =  bike_name == 'Moustache'
            if is_ebike:
                print("     One short ride set to private EBike")
                activity = client.update_activity(activity_id=activity.id, sport_type="EBikeRide", private=True)
            else:
                print(f"    commuting activity not set to EBike as bike is: {bike_name}")
            nb_rides_edited += 1
            
        if activity.type == "Workout":
            if not activity.private:
                print("     One public workout set to private")
                client.update_activity(activity_id=activity.id, private=True, name = "Yoga", sport_type = "Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            else:
                client.update_activity(activity_id=activity.id, name = "Yoga", sport_type = "Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            
        if activity.type == "Yoga":
            if not activity.private:
                print("     One public yoga workout set to private")
                updated_activity = client.update_activity(activity_id=activity.id, private=True, name = "Yoga")
                nb_workout_edited += 1
                
        if activity.type == "EBikeRide":
            if not activity.private:
                print("     One public e-bike ride set to private")
                client.update_activity(activity_id=activity.id, private=True)
                nb_rides_edited += 1
                
        if activity.type == 'Ride':
            if activity.start_date_local.year < 2021:
                continue
            this_ride_kms = int(activity.distance / 1000.0)
            if this_ride_kms > 30:
                bike_name = get_gear_name(client, activity.gear_id)
                if bike_name == "Moustache":
                    logging.error("Moustache e-bike is associated to a ride > 30 kms")
            ride_kms = ride_kms + this_ride_kms

    checkpoint_handle.close()
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