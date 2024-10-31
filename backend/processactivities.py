from datetime import timedelta
import json
import logging
from stravalib.util import limiter
from stravalib import exc



GEAR_ID_2_NAME = {}

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

    already_parsed_activities = dict()
    # try:
        # already_parsed_activities_file = open("activities.json")
        # already_parsed_activities = json.load(already_parsed_activities_file)
    # except:
        # pass

    first_date = "2024-06-01"
    commuting_threshold = timedelta(minutes=45)
    activities = client.get_activities(after=first_date)
    nb_rides_edited = 0
    nb_workout_edited = 0
    nb_activity = 0
    ride_kms = 0
    for activity in activities:
        if str(activity.id) in already_parsed_activities.keys():
            continue
        already_parsed_activities[str(activity.id)] = True
        nb_activity += 1
        try:
            print (activity.type.root, activity.name, activity.start_date, activity.elapsed_time, activity.private)
        except:
            print (activity.type.root, activity.name, activity.start_date, activity.elapsed_time, activity.private)
            
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
        if activity.type.root == "Workout":
            if not activity.private:
                print("     One public workout set to private")
                client.update_activity(activity_id=activity.id, private=True, name = "Yoga", sport_type = "Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            else:
                client.update_activity(activity_id=activity.id, name = "Yoga", sport_type = "Yoga")
                print("     One workout set to yoga")
                nb_workout_edited += 1
            
        if activity.type.root == "Yoga":
            if not activity.private:
                print("     One public yoga workout set to private")
                updated_activity = client.update_activity(activity_id=activity.id, private=True, name = "Yoga")
                nb_workout_edited += 1
        if activity.type.root == "EBikeRide":
            if not activity.private:
                print("     One public e-bike ride set to private")
                client.update_activity(activity_id=activity.id, private=True)
                nb_rides_edited += 1
        if activity.type.root == 'Ride':
            if activity.start_date_local.year < 2021:
                continue
            ride_kms = ride_kms + int(activity.distance / 1000.0)

    with open("activities.json", "w") as already_parsed_activities_file:
        json.dump(already_parsed_activities, already_parsed_activities_file)    
            
    print("#rides > {fd} kms: {rk}".format(fd=first_date, rk=ride_kms))
    print("#rides edited: ", nb_rides_edited)
    print( "#workout edited: ", nb_workout_edited)
    print("#activities: ", nb_activity)

    return {
        "nb_activity": nb_activity,
        "nb_workout_edited": nb_workout_edited,
        "nb_ride_edited": nb_rides_edited
    }